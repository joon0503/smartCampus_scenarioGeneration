# DQN model to solve vehicle control problem
import datetime
import math
import os
import pickle
import random
import re
import sys
import time
from argparse import ArgumentParser
from collections import deque

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pybullet as p
import pybullet_data
import tensorflow as tf
from icecream import ic

from utils.experience_replay import Memory, SumTree
from utils.rl_dqn import QAgent
from utils.rl_icm import ICM
from utils.scene_constants_pb import scene_constants
from utils.utils_data import data_pack
from utils.utils_pb import (detectCollision, detectReachedGoal, getVehicleState, initQueue, resetQueue)
from utils.utils_pb_scene_2LC import genScene, initScene, removeScene

def get_options():
    parser = ArgumentParser(
        description='File for learning'
        )
    parser.add_argument('--MAX_EPISODE', type=int, default=10001,
                        help='max number of episodes iteration\n')
    parser.add_argument('--MAX_TIMESTEP', type=int, default=1000,
                        help='max number of time step of simulation per episode')
    parser.add_argument('--ACTION_DIM', type=int, default=5,
                        help='number of actions one can take')
    parser.add_argument('--OBSERVATION_DIM', type=int, default=11,
                        help='number of observations one can see')
    parser.add_argument('--GAMMA', type=float, default=0.99,
                        help='discount factor of Q learning')
    parser.add_argument('--INIT_EPS', type=float, default=1.0,
                        help='initial probability for randomly sampling action')
    parser.add_argument('--FINAL_EPS', type=float, default=1e-1,
                        help='finial probability for randomly sampling action')
    parser.add_argument('--EPS_DECAY', type=float, default=0.995,
                        help='epsilon decay rate')
    parser.add_argument('--EPS_ANNEAL_STEPS', type=int, default=2000,
                        help='steps interval to decay epsilon')
    parser.add_argument('--LR', type=float, default=1e-4,
                        help='learning rate')
    parser.add_argument('--MAX_EXPERIENCE', type=int, default=1000,
                        help='size of experience replay memory')
    parser.add_argument('--SAVER_RATE', type=int, default=500,
                        help='Save network after this number of episodes')
    parser.add_argument('--TARGET_UPDATE_STEP', type=int, default=3000,
                        help='Number of steps required for target update')
    parser.add_argument('--BATCH_SIZE', type=int, default=32,
                        help='mini batch size'),
    parser.add_argument('--H1_SIZE', type=int, default=80,
                        help='size of hidden layer 1')
    parser.add_argument('--H2_SIZE', type=int, default=80,
                        help='size of hidden layer 2')
    parser.add_argument('--H3_SIZE', type=int, default=40,
                        help='size of hidden layer 3')
    parser.add_argument('--RESET_STEP', type=int, default=10000,
                        help='number of episode after resetting the simulation')
    parser.add_argument('--RUNNING_AVG_STEP', type=int, default=100,
                        help='number of episode to calculate the average score')
    parser.add_argument('--manual','-m', action='store_true',
                        help='Step simulation manually')
    parser.add_argument('--NO_SAVE','-us', action='store_true',
                        help='Use saved tensorflow network')
    parser.add_argument('--TESTING','-t', action='store_true',
                        help='No training. Just testing. Use it with eps=1.0')
    parser.add_argument('--disable_DN', action='store_true',
                        help='Disable the usage of double network.')
    parser.add_argument('--enable_PER', action='store_true', default = False,
                        help='Enable the usage of PER.')
    parser.add_argument('--enable_GUI', action='store_true', default = False,
                        help='Enable the GUI.')
    parser.add_argument('--disable_duel', action='store_true',
                        help='Disable the usage of double network.')
    parser.add_argument('--FRAME_COUNT', type=int, default=1,
                        help='Number of frames to be used')
    parser.add_argument('--ACT_FUNC', type=str, default='relu',
                        help='Activation function')
    parser.add_argument('--GOAL_REW', type=int, default=500,
                        help='Activation function')
    parser.add_argument('--FAIL_REW', type=int, default=-2000,
                        help='Activation function')
    parser.add_argument('--VEH_COUNT', type=int, default=10,
                        help='Number of vehicles to use for simulation')
    parser.add_argument('--INIT_SPD', type=int, default=2,
                        help='Initial speed of vehicle in  km/hr')
    parser.add_argument('--DIST_MUL', type=int, default=20,
                        help='Multiplier for rewards based on the distance to the goal')
    parser.add_argument('--EXPORT', action='store_true', default=False,
                        help='Export the weights into a csv file')
    parser.add_argument('--SEED', type=int, default=1,
                        help='Set simulation seed')
    parser.add_argument('--CTR_FREQ', type=float, default=0.2,
                        help='Control frequency in seconds. Upto 0.001 seconds')
    parser.add_argument('--MIN_LIDAR_CONST', type=float, default=-0.075,
                        help='Stage-wise reward 1/(min(lidar)+MIN_LIDAR_CONST) related to minimum value of LIDAR sensor')
    parser.add_argument('--L2_LOSS', type=float, default=0.0,
                        help='Scale of L2 loss')
    parser.add_argument('--FIX_INPUT_STEP', type=int, default=4,
                        help='Fix input steps')
    parser.add_argument('--X_COUNT', type=int, default=6,
                        help='Width of the grid for vehicles. Default of 5 means we lay down 5 vehicles as the width of the grid')
    options = parser.parse_args()

    return parser, options


##################################
# TENSORFLOW HELPER
##################################

def printTFvars():
    print("==Training==")
    tvars = tf.trainable_variables(scope='Training')

    for var in tvars:
        print(var)

    print("==Target==")
    tvars = tf.trainable_variables(scope='Target')

    for var in tvars:
        print(var)
    print("=========")

    return


##################################
# GENERAL
##################################

# From sensor and goal queue, get observation.
# observation is a row vector with all frames of information concatentated to each other
# Recall that queue stores 2*FRAME_COUNT of information. 
# first = True: get oldest info
# first = False: get latest info
def getObs( sensor_queue, goal_queue, old=True):

    if old == True:
        sensor_stack    = np.concatenate(sensor_queue)[0:scene_const.sensor_count*options.FRAME_COUNT]
        goal_stack      = np.concatenate(goal_queue)[0:2*options.FRAME_COUNT]
        observation     = np.concatenate((sensor_stack, goal_stack))    
    else:
        sensor_stack    = np.concatenate(sensor_queue)[scene_const.sensor_count*options.FRAME_COUNT:]
        goal_stack      = np.concatenate(goal_queue)[2*options.FRAME_COUNT:]
        observation     = np.concatenate((sensor_stack, goal_stack))    

    return observation

# Calculate Approximate Rewards for variaous cases
def printRewards( scene_const, options ):
    # Some parameters
    veh_speed = options.INIT_SPD/3.6  # 10km/hr in m/s

    # Time Steps
    #dt_code = scene_const.dt * options.FIX_INPUT_STEP

    # Expected Total Time Steps
    total_step = (scene_const.goal_distance/veh_speed)*(1/options.CTR_FREQ)

    # Reward at the end
    rew_end = 0
    for i in range(0, int(total_step)):
        goal_distance = scene_const.goal_distance - i*options.CTR_FREQ*veh_speed 
        if i != total_step-1:
            rew_end = rew_end -options.DIST_MUL*(goal_distance/scene_const.goal_distance)**2*(options.GAMMA**i) 
        else:
            rew_end = rew_end + options.GOAL_REW*(options.GAMMA**i) 

    # Reward at Obs
    rew_obs = 0
    for i in range(0, int(total_step*0.5)):
        goal_distance = scene_const.goal_distance - i*options.CTR_FREQ*veh_speed 
        if i != int(total_step*0.5)-1:
            rew_obs = rew_obs -options.DIST_MUL*(goal_distance/scene_const.goal_distance)**2*(options.GAMMA**i) 
        else:
            rew_obs = rew_obs + options.FAIL_REW*(options.GAMMA**i) 

    # Reward at 75%
    rew_75 = 0
    for i in range(0, int(total_step*0.75)):
        goal_distance = scene_const.goal_distance - i*options.CTR_FREQ*veh_speed 
        if i != int(total_step*0.75)-1:
            rew_75 = rew_75 -options.DIST_MUL*(goal_distance/scene_const.goal_distance)**2*(options.GAMMA**i) 
        else:
            rew_75 = rew_75 + options.FAIL_REW*(options.GAMMA**i) 

    # Reward at 25%
    rew_25 = 0
    for i in range(0, int(total_step*0.25)):
        goal_distance = scene_const.goal_distance - i*options.CTR_FREQ*veh_speed 
        if i != int(total_step*0.25)-1:
            rew_25 = rew_25 -options.DIST_MUL*(goal_distance/scene_const.goal_distance)**2*(options.GAMMA**i) 
        else:
            rew_25 = rew_25 + options.FAIL_REW*(options.GAMMA**i) 

    # EPS Info
    

    ########
    # Print Info
    ########

    print("======================================")
    print("======================================")
    print("        REWARD ESTIMATION")
    print("======================================")
    print("Control Frequency (s)  : ", options.CTR_FREQ)
    print("Expected Total Step    : ", total_step)
    print("Expected Reward (25)   : ", rew_25)
    print("Expected Reward (Obs)  : ", rew_obs)
    print("Expected Reward (75)   : ", rew_75)
    print("Expected Reward (Goal) : ", rew_end)
    print("======================================")
    print("        EPS ESTIMATION")
    print("Expected Step per Epi  : ", total_step*0.5)
    print("Total Steps            : ", total_step*0.5*options.MAX_EPISODE)
    print("EPS at Last Episode    : ", options.INIT_EPS*options.EPS_DECAY**(total_step*0.5*options.MAX_EPISODE/options.EPS_ANNEAL_STEPS)  )
    print("======================================")
    print("======================================")


    return

def printSpdInfo():
    desiredSpd = options.INIT_SPD

    wheel_radius = 0.63407*0.5      # Wheel radius in metre

    desiredSpd_rps = desiredSpd*(1000/3600)*(1/wheel_radius)   # km/hr into radians per second

    print("Desired Speed: " + str(desiredSpd) + " km/hr = " + str(desiredSpd_rps) + " radians per seconds = " + str(math.degrees(desiredSpd_rps)) + " degrees per seconds. = " + str(desiredSpd*(1000/3600)) + "m/s" )

    return


# Update Camera
# Input
#   cam_pos  :  [x,y,z], camera target position
#   cam_dist :  camera distance
# Output
#   cam_pos : new camera position
#   cam_dist : new camerad distance
def controlCamera(cam_pos, cam_dist):
    # get keys
    keys = p.getKeyboardEvents()

    if keys.get(49):  #1
      cam_pos[0] = cam_pos[0] - 1
    if keys.get(50):  #2
      cam_pos[0] = cam_pos[0] + 1
    if keys.get(51):  #3
      cam_pos[1] = cam_pos[1] + 1
    if keys.get(52):  #4
      cam_pos[1] = cam_pos[1] - 1
    if keys.get(53):  #5
      cam_pos = [0,0,0]
      cam_dist = 5
    if keys.get(54):  #6
      cam_dist = cam_dist + 1
    if keys.get(55):  #7
      cam_dist = cam_dist - 1
    p.resetDebugVisualizerCamera( cameraDistance = cam_dist, cameraYaw = 0, cameraPitch = -89, cameraTargetPosition = cam_pos )


    return cam_pos, cam_dist

# Draw Debug Lines
# Input
#   ray_batch_result: result from raytest batch 
#   sensor_data
#   createInit : create initial debug lines
# Output
#   rayIds : 2d array for ray id. each row is ray ids for a single vehicle
def drawDebugLines( options, scene_const, vehicle_handle, sensor_data = -1, ray_id = -1, createInit = False, ray_width = 2, rayHitColor = [1,0,0], rayMissColor = [0,1,0]):
    # Paremters?
    rayIds=[]                   # 2d array for ray id
    # rayHitColor = [1,0,0]
    # rayMissColor = [0,1,0]
    hokuyo_joint = 8

    # for each vehicle
    for k in range (options.VEH_COUNT):
        rayIds.append([])
        # for each sensor
        for i in range (scene_const.sensor_count):
            # Reference is : y-axis for horizontal, +ve is left.   x-axis for vertical, +ve is up
            # curr_angle = scene_const.sensor_max_angle - i*scene_const.sensor_delta

            # No result just draw
            if createInit == True:
                rayIds[k].append(p.addUserDebugLine(scene_const.rayFrom[i], scene_const.rayTo[i], rayMissColor,parentObjectUniqueId=vehicle_handle[k], parentLinkIndex=hokuyo_joint ))
            else:
                # Draw
                hit_fraction = sensor_data[k][i]
                if hit_fraction == 1:      # If hit nothing
                    ray_id[k][i] = p.addUserDebugLine(scene_const.rayFrom[i], scene_const.rayTo[i], rayMissColor,parentObjectUniqueId=vehicle_handle[k], parentLinkIndex=hokuyo_joint, replaceItemUniqueId = ray_id[k][i], lineWidth = ray_width  )
                else:
                    local_hit = np.asarray(scene_const.rayFrom[i]) + hit_fraction*(np.asarray(scene_const.rayTo[i]) - np.asarray(scene_const.rayFrom[i]) )
                    ray_id[k][i] = p.addUserDebugLine(scene_const.rayFrom[i], local_hit, rayHitColor,parentObjectUniqueId=vehicle_handle[k], parentLinkIndex=hokuyo_joint, replaceItemUniqueId = ray_id[k][i], lineWidth = ray_width )

    if ray_id == -1: 
        return rayIds
    else:
        return ray_id


########################
# MAIN
########################
if __name__ == "__main__":
    # Print Options
    parser, options = get_options()
    print(str(options).replace(" ",'\n'))

    # Check Inputs
    if options.TARGET_UPDATE_STEP % options.VEH_COUNT != 0:
        raise ValueError('VEH_COUNT must divide TARGET_UPDATE_STEPS')

    # Set Seed
    np.random.seed(1)
    random.seed(1)
    tf.set_random_seed(1)

    # Set print options
    np.set_printoptions( precision = 4, linewidth = 100 )

    # For interactive plot
    plt.ion()

    ######################################33
    # SET 'GLOBAL' Variables
    ######################################33
    START_TIME       = datetime.datetime.now() 
    START_TIME_STR   = str(START_TIME).replace(" ","_")
    START_TIME_STR   = str(START_TIME).replace(":","_")

    # Randomize obstacle position at initScene
    RANDOMIZE = True

    # Simulation Setup
    # Get client ID
    if options.enable_GUI == True:
        clientID = p.connect(p.GUI)
        p.resetDebugVisualizerCamera( cameraDistance = 5, cameraYaw = 0, cameraPitch = -89, cameraTargetPosition = [0,0,0] )
        cam_pos = [0,0,0]
        cam_dist = 5
    else:
        clientID = p.connect(p.DIRECT)

    if clientID < 0:
        print("ERROR: Cannot establish connection to PyBullet.")
        sys.exit()

    p.resetSimulation()
    p.setRealTimeSimulation( 0 )        # Don't use real time simulation
    p.setGravity(0, 0, -9.8)
    p.setTimeStep( 1/60 )

    # Set scene_constants
    scene_const                     = scene_constants()
    scene_const.clientID            = clientID

    # Save options
    if not os.path.exists("./checkpoints-vehicle"):
        os.makedirs("./checkpoints-vehicle")

    if options.TESTING == True:
        option_file = open("./checkpoints-vehicle/options_TESTING_"+START_TIME_STR+'.txt', "w")
    else:
        option_file = open("./checkpoints-vehicle/options_"+START_TIME_STR+'.txt', "w")

    # For each option
    for x in sorted(vars(options).keys()):
        option_file.write( str(x).ljust(20) + ": " + str(vars(options)[x]).ljust(10) )   # write option
        if vars(options)[x] == parser.get_default(x):       # if default value
            option_file.write( '(DEFAULT)' )                # say it is default
        option_file.write('\n')
    option_file.close()

    # Print Rewards
    printRewards( scene_const, options )

    # Print Speed Infos
    printSpdInfo()

    ###########################
    # Scene Generation & Handles
    ###########################
    # -------------------------
    # Handles
    # -------------------------
    # Create empty handle list & dict
    vehicle_handle      = np.zeros(options.VEH_COUNT, dtype=int)
    dummy_handle        = np.zeros(options.VEH_COUNT, dtype=int)
    case_wall_handle    = np.zeros((options.VEH_COUNT,scene_const.wall_cnt), dtype=int) 
    motor_handle        = [2, 3]
    steer_handle        = [4, 6]

    # Make handle into dict to be passed around functions
    handle_dict = {
        # 'sensor'    : sensor_handle,
        'motor'     : motor_handle,
        'steer'     : steer_handle,
        'vehicle'   : vehicle_handle,
        'dummy'     : dummy_handle,
        'wall'      : case_wall_handle,
        # 'obstacle'  : obs_handle
    }

    # -------------------------
    # Scenartion Generation
    # -------------------------

    # Load plane
    p.loadURDF(os.path.join(pybullet_data.getDataPath(), "plane100.urdf"))

    # Generate Scene and get handles
    handle_dict = genScene( scene_const, options, handle_dict, range(0,options.VEH_COUNT) )

    # Draw initial lines
    if options.enable_GUI == True:
        sensor_handle = drawDebugLines( options, scene_const, vehicle_handle, createInit = True )
        collision_handle = drawDebugLines( options, scene_const, vehicle_handle, createInit = True )

    # Print Handles
    ic(handle_dict)

    print("Getting handles...")
    # motor_handle, steer_handle = getMotorHandles( options, scene_const )
    # sensor_handle = getSensorHandles( options, scene_const )


    ########################
    # Initialize Test Scene
    ########################

    # Data
    sensorData      = np.zeros(scene_const.sensor_count)   

    ##############
    # TF Setup
    ##############
    # Define placeholders to catch inputs and add options
    agent_train     = QAgent(options,scene_const, 'Training')
    agent_target    = QAgent(options,scene_const, 'Target')
    agent_icm       = ICM(options,scene_const,'icm_Training')

    sess            = tf.InteractiveSession()
    rwd             = tf.placeholder(tf.float32, [None, ], name='reward')

    # Copying Variables (taken from https://github.com/akaraspt/tiny-dqn-tensorflow/blob/master/main.py)
    target_vars = agent_target.getTrainableVarByName()
    online_vars = agent_train.getTrainableVarByName()

    copy_ops = [target_var.assign(online_vars[var_name]) for var_name, target_var in target_vars.items()]
    copy_online_to_target = tf.group(*copy_ops)
        
    sess.run(tf.global_variables_initializer())
    copy_online_to_target.run()         # Copy init weights

    # saving and loading networks
    if options.NO_SAVE == False:
        saver = tf.train.Saver( max_to_keep = 100 )
        checkpoint = tf.train.get_checkpoint_state("checkpoints-vehicle")
        if checkpoint and checkpoint.model_checkpoint_path:
            saver.restore(sess, checkpoint.model_checkpoint_path)
            print("=================================================")
            print("Successfully loaded:", checkpoint.model_checkpoint_path)
            print("=================================================")
        else:
            print("=================================================")
            print("Could not find old network weights")
            print("=================================================")

    
    # Some initial local variables
    feed = {}
    feed_icm = {}
    eps = options.INIT_EPS
    global_step = 0

    # The replay memory.
    if options.enable_PER == False:
        # Don't use PER
        print("=================================================")
        print("NOT using PER!")
        print("=================================================")
        replay_memory = Memory(options.MAX_EXPERIENCE)
    else:
        # Use PER
        print("=================================================")
        print("Using PER!")
        print("=================================================")
        replay_memory = Memory(options.MAX_EXPERIENCE, disable_PER = False, absolute_error_upperbound = 2000)
        

    # Print trainable variables
    printTFvars()

    # Export weights
    if options.EXPORT == True:
        print("Exporting weights...")
        val = tf.trainable_variables(scope='Training')
        for v in val:
            fixed_name = str(v.name).replace('/','_')
            fixed_name = str(v.name).replace(':','_')
            np.savetxt( './model_weights/' + fixed_name + '.txt', sess.run([v])[0], delimiter=',')
        sys.exit() 


    ########################
    # END TF SETUP
    ########################

    ###########################        
    # DATA VARIABLES
    ###########################        
    data_package = data_pack( START_TIME_STR )    

    reward_data         = np.empty(0)
    avg_loss_value_data = np.empty(1)
    avg_epi_reward_data = np.zeros(options.MAX_EPISODE)
    track_eps           = []
    track_eps.append((0,eps))

    ###########################        
    # Initialize Variables
    ###########################        
   
    # Some variables
    reward_stack        = np.zeros(options.VEH_COUNT)                              # Holds rewards of current step
    action_stack        = np.zeros(options.VEH_COUNT)                              # action_stack[k] is the array of optinos.ACTION_DIM with each element representing the index
    epi_step_stack      = np.zeros(options.VEH_COUNT)                              # Count number of step for each vehicle in each episode
    epi_reward_stack    = np.zeros(options.VEH_COUNT)                              # Holds reward of current episode
    epi_counter         = 0                                                        # Counts # of finished episodes
    epi_done            = np.zeros(options.VEH_COUNT) 
    eps_tracker         = np.zeros(options.MAX_EPISODE+options.VEH_COUNT+1)
    last_saved_epi = 0                                                             # variable used for checking when to save
 
    # Initialize Scene
    initScene( scene_const, options, list(range(0,options.VEH_COUNT)), handle_dict, randomize = RANDOMIZE)               # initialize

    # List of deque to store data
    sensor_queue = []
    goal_queue   = []
    for i in range(0,options.VEH_COUNT):
        sensor_queue.append( deque() )
        goal_queue.append( deque() )

    # initilize them with initial data
    veh_pos, veh_heading, dDistance, gInfo = getVehicleState( scene_const, options, handle_dict )
    sensor_queue, goal_queue = initQueue( options, sensor_queue, goal_queue, dDistance, gInfo )

    ##############################
    # MAIN SIMULATION LOOP
    ##############################
    # while ( True ):
    #     GS_START_TIME_STR   = datetime.datetime.now()
    #     if options.enable_GUI == True:
    #         cam_pos, cam_dist = controlCamera( cam_pos, cam_dist )  
    #     p.stepSimulation()

    #     # Draw Debug Lines
    #     if options.enable_GUI == True:
    #         sensor_handle = drawDebugLines(options, scene_const, vehicle_handle, dDistance, sensor_handle )

    #     veh_pos, veh_heading, dDistance, gInfo = getVehicleState( scene_const, options, handle_dict )

    #     # Sleep
    #     time.sleep(0.01)
    #     GS_END_TIME_STR   = datetime.datetime.now()
    #     print('Time : ' + str(GS_END_TIME_STR - GS_START_TIME_STR))
    #     # pass




    # Global Step Loop
    while epi_counter <= options.MAX_EPISODE:
        # GS_START_TIME_STR   = datetime.datetime.now()
        if options.enable_GUI == True and options.manual == False:
            cam_pos, cam_dist = controlCamera( cam_pos, cam_dist )  
            time.sleep(0.01)
        # Decay epsilon
        global_step += options.VEH_COUNT
        if global_step % options.EPS_ANNEAL_STEPS == 0 and eps > options.FINAL_EPS:
            eps = eps * options.EPS_DECAY
            # Save eps for plotting
            #track_eps.append((epi_counter+1,eps)) 

        #print("=====================================")
        #print("Global Step: " + str(global_step) + 'EPS: ' + str(eps) + ' Finished Episodes:' + str(epi_counter) )


        ####
        # Find & Apply Action
        ####
        # FIXME: This can be made faster by not using loop and just pushing through network all at once
        obs_stack = np.empty((options.VEH_COUNT, (scene_const.sensor_count+2)*options.FRAME_COUNT))

        # Get observation stack (which is used in getting the action) 
        for v in range(0,options.VEH_COUNT):
            # Get current info to generate input
            obs_stack[v]    = getObs( sensor_queue[v], goal_queue[v], old=False)

        # Get optimal action. 
        action_stack = agent_train.sample_action(
                                            {
                                                agent_train.observation : obs_stack
                                            },
                                            eps,
                                            options,
                                            False
                                            )

        # Apply the Steering Action & Keep Velocity. For some reason, +ve means left, -ve means right
        targetSteer = scene_const.max_steer - action_stack * abs(scene_const.max_steer - scene_const.min_steer)/(options.ACTION_DIM-1)
        # ic(action_stack)
        # ic(targetSteer)
        #steeringSlider = p.addUserDebugParameter("steering", -2, 2, 0)
        #steeringAngle = p.readUserDebugParameter(steeringSlider)
        for veh_index in range(options.VEH_COUNT):
            p.setJointMotorControlArray( vehicle_handle[veh_index], steer_handle, p.POSITION_CONTROL, targetPositions = np.repeat(targetSteer[veh_index],len(steer_handle)) )
            p.setJointMotorControlArray( vehicle_handle[veh_index], motor_handle, p.VELOCITY_CONTROL, targetVelocities = np.repeat(options.INIT_SPD,len(motor_handle)) )

        ####
        # Step
        ####

        for q in range(0,options.FIX_INPUT_STEP):
            p.stepSimulation()

        if options.manual == True:
            input('Press Enter')

        ####
        # Get Next State
        ####
        next_veh_pos, next_veh_heading, next_dDistance, next_gInfo = getVehicleState( scene_const, options, handle_dict )

        #print('--------------------------')
        #ic(next_veh_pos)
        #ic(next_veh_heading)
        #ic(next_dDistance)
        #ic(next_gInfo)
        #print('--------------------------')

        for v in range(0,options.VEH_COUNT):
            # Get new Data
            #veh_pos_queue[v].append(next_veh_pos[v])   

            # Update queue
            sensor_queue[v].append(next_dDistance[v])
            sensor_queue[v].popleft()
            goal_queue[v].append(next_gInfo[v])
            goal_queue[v].popleft()

            # Get reward for each vehicle
            #reward_stack[v] = -(options.DIST_MUL+1/(next_dDistance[v].min()+options.MIN_LIDAR_CONST))*next_gInfo[v][1]**2 + 3*( -5 + (10/(options.ACTION_DIM-1))*np.argmin( action_stack[v] ) )
            reward_stack[v] = -(options.DIST_MUL + 1/(next_dDistance[v].min()+options.MIN_LIDAR_CONST))*next_gInfo[v][1]**2 + 3*( -5 + (10/(options.ACTION_DIM-1))*np.argmin( action_stack[v] ) )
            # reward_stack[v] = -(options.DIST_MUL)*next_gInfo[v][1]**2
            # cost is the distance squared + inverse of minimum LIDAR distance

        # Draw Debug Lines
        if options.enable_GUI == True:
            # Draw Lidar
            sensor_handle = drawDebugLines(options, scene_const, vehicle_handle, next_dDistance, sensor_handle, createInit = False )

            # Draw Collision Range
            collision_handle = drawDebugLines(options, scene_const, vehicle_handle, np.ones((options.VEH_COUNT,scene_const.sensor_count))*(scene_const.collision_distance/scene_const.sensor_distance), collision_handle, createInit = False, ray_width = 4, rayHitColor = [0,0,0] )

        #######
        # Test Estimation
        #######
        if options.TESTING == True:
            v = 1

            # Print curr & next state
            curr_state     = getObs( sensor_queue[v], goal_queue[v], old=True)
            next_state     = getObs( sensor_queue[v], goal_queue[v], old=False)
            #print('curr_state:', curr_state)
            #print('next_state:', next_state)
            #print('estimate  :', agent_icm.getEstimate( {agent_icm.observation : np.reshape(np.concatenate([curr_state, action_stack[v]]), [-1, 16])  }  ) )
            #print('')
            agent_icm.plotEstimate( scene_const, options, curr_state, action_stack[v], next_veh_heading[v], agent_train, save=True, ref = 'vehicle')

            
        ###
        # Handle Events
        ###
        
        # Reset Done
        epi_done = np.zeros(options.VEH_COUNT)

        # List of resetting vehicles
        reset_veh_list = []

        # Find reset list 
        for v in range(0,options.VEH_COUNT):
            # If vehicle collided, give large negative reward
            collision_detected, collision_sensor = detectCollision(next_dDistance[v], scene_const)
            if collision_detected == True:
                print('-----------------------------------------')
                print('Vehicle #' + str(v) + ' collided! Detected Sensor : ' + str(collision_sensor) )
                print('-----------------------------------------')
                
                # Print last Q-value 
                # observation     = getObs( sensor_queue[v], goal_queue[v], old=False)
                # curr_q_value = sess.run([agent_train.output], feed_dict = {agent_train.observation : np.reshape(observation, (1, -1))})
                # print(curr_q_value)

                # Add this vehicle to list of vehicles to reset
                reset_veh_list.append(v)

                # Set flag and reward, and save eps
                reward_stack[v] = options.FAIL_REW
                eps_tracker[epi_counter] = eps
                #if global_step >= options.MAX_EXPERIENCE:
                epi_counter += 1

                # Set done
                epi_done[v] = 1
                # If collided, skip checking for goal point
                continue

            # If vehicle is at the goal point, give large positive reward
            if detectReachedGoal(next_veh_pos[v], next_gInfo[v], next_veh_heading[v], scene_const):
                print('-----------------------------------------')
                print('Vehicle #' + str(v) + ' reached goal point')
                print('-----------------------------------------')
                
                # Reset Simulation
                reset_veh_list.append(v)

                # Set flag and reward
                reward_stack[v] = options.GOAL_REW
                eps_tracker[epi_counter] = eps
                #if global_step >= options.MAX_EXPERIENCE:
                epi_counter += 1

                # Set done
                epi_done[v] = 1

            # If over MAXSTEP
            if epi_step_stack[v] > options.MAX_TIMESTEP:
                print('-----------------------------------------')
                print('Vehicle #' + str(v) + ' over max step')
                print('-----------------------------------------')

                # Reset Simulation
                reset_veh_list.append(v)

                eps_tracker[epi_counter] = eps
                #if global_step >= options.MAX_EXPERIENCE:
                epi_counter += 1
                

        # Detect being stuck
        #   Not coded yet.
        
        ###########
        # START LEARNING
        ###########

        # Add latest information to memory
        for v in range(0,options.VEH_COUNT):
            # Get observation
            observation             = getObs( sensor_queue[v], goal_queue[v], old = True)
            next_observation        = getObs( sensor_queue[v], goal_queue[v], old = False)

            # Add experience. (observation, action in one hot encoding, reward, next observation, done(1/0) )
            #experience = observation, action_stack[v], reward_stack[v], next_observation, epi_done[v]
            experience = observation, action_stack[v], reward_stack[v], next_observation, epi_done[v]
            #print('experience', experience)
           
            # Save new memory 
            replay_memory.store(experience)

        # Start training
        if global_step >= options.MAX_EXPERIENCE and options.TESTING == False:
            for tf_train_counter in range(0,options.VEH_COUNT):
                # Obtain the mini batch. (Batch Memory is '2D array' with BATCH_SIZE X size(experience)
                tree_idx, batch_memory, ISWeights_mb = replay_memory.sample(options.BATCH_SIZE)

                # Get state/action/next state from obtained memory. Size same as queues
                states_mb       = np.array([each[0][0] for each in batch_memory])           # BATCH_SIZE x STATE_DIM 
                actions_mb      = np.array([each[0][1] for each in batch_memory])           # BATCH_SIZE x ACTION_DIM
                rewards_mb      = np.array([each[0][2] for each in batch_memory])           # 1 x BATCH_SIZE
                next_states_mb  = np.array([each[0][3] for each in batch_memory])   
                done_mb         = np.array([each[0][4] for each in batch_memory])   

                # actions mb is list of numbers. Need to change it into one hot encoding
                actions_mb_hot = np.zeros((options.BATCH_SIZE,options.ACTION_DIM))
                actions_mb_hot[np.arange(options.BATCH_SIZE),np.asarray(actions_mb, dtype=int)] = 1

                # actions converted to value array
                #actions_mb_val = oneHot2Angle( actions_mb_hot, scene_const, options, radians = False, scale = True )

                # Get Target Q-Value
                feed.clear()
                feed.update({agent_train.observation : next_states_mb})

                # Calculate Target Q-value. Uses double network. First, get action from training network
                action_train = np.argmax( agent_train.output.eval(feed_dict=feed), axis=1 )

                if options.disable_DN == False:
                    feed.clear()
                    feed.update({agent_target.observation : next_states_mb})

                    # Using Target + Double network
                    q_target_val = rewards_mb + options.GAMMA * agent_target.output.eval(feed_dict=feed)[np.arange(0,options.BATCH_SIZE),action_train]
                else:
                    feed.clear()
                    feed.update({agent_target.observation : next_states_mb})

                    # Just using Target Network.
                    q_target_val = rewards_mb + options.GAMMA * np.amax( agent_target.output.eval(feed_dict=feed), axis=1)
           
                # set q_target to reward if episode is done
                for v_mb in range(0,options.BATCH_SIZE):
                    if done_mb[v_mb] == 1:
                        q_target_val[v_mb] = rewards_mb[v_mb]

                #print('q_target_val', q_target_val) 
                #print("\n\n")


                # Gradient Descent
                feed.clear()
                feed.update({agent_train.observation : states_mb})
                feed.update({agent_train.act : actions_mb_hot})
                feed.update({agent_train.target_Q : q_target_val } )        # Add target_y to feed
                feed.update({agent_train.ISWeights : ISWeights_mb   })

                #with tf.variable_scope("Training"):   
                # Train RL         
                step_loss_per_data, step_loss_value, _  = sess.run([agent_train.loss_per_data, agent_train.loss, agent_train.optimizer], feed_dict = feed)


                # Train forward model
                feed_icm.clear()
                feed_icm.update({agent_icm.observation  : np.concatenate([states_mb, actions_mb_hot],-1) } )
                feed_icm.update({agent_icm.actual_state : next_states_mb})
                #print(feed_icm)
                icm_loss, _                             = sess.run([agent_icm.loss, agent_icm.optimizer], feed_dict = feed_icm)
                #print('icm_loss:', icm_loss)


                #print(rewards_mb)
                #print(step_loss_per_data)

                # Use sum to calculate average loss of this episode.
                data_package.add_loss( np.mean(step_loss_per_data) )

                #if tf_train_counter == 0:
                    #print(step_loss_per_data)
        
                # Update priority
                replay_memory.batch_update(tree_idx, step_loss_per_data)
        else:
            # If just running to get memory, do not increment counter
            epi_counter = 0

        # Remove Scene
        handle_dict = removeScene( scene_const, options, reset_veh_list, handle_dict )

        # Generate Scene again with updated lane_width
        scene_const.lane_width = np.random.random_sample()*4.5 + 3.5
        handle_dict = genScene( scene_const, options, handle_dict, reset_veh_list, genVehicle = False )

        # Reset Vehicles    
        initScene( scene_const, options, reset_veh_list, handle_dict, randomize = RANDOMIZE)               # initialize

        # Reset data queue
        _, _, reset_dDistance, reset_gInfo = getVehicleState( scene_const, options, handle_dict)
        sensor_queue, goal_queue = resetQueue( options, sensor_queue, goal_queue, reset_dDistance, reset_gInfo, reset_veh_list )

        ###############
        # Miscellaneous
        ###############
        # Update Target
        if global_step % options.TARGET_UPDATE_STEP == 0:
            print('-----------------------------------------')
            print("Updating Target network.")
            print('-----------------------------------------')
            copy_online_to_target.run()

        # Update rewards
        for v in range(0,options.VEH_COUNT):
            # print('Vehicle ' + str(v) + ' reward_stack[v]' + str(reward_stack[v]))
            epi_reward_stack[v] = epi_reward_stack[v] + reward_stack[v]*(options.GAMMA**epi_step_stack[v])

        # Print Rewards
        for v in reset_veh_list:
            print('========')
            print('Vehicle #:', v)
            print('\tGlobal Step:' + str(global_step))
            print('\tEPS: ' + str(eps))
            print('\tEpisode #: ' + str(epi_counter) + ' / ' + str(options.MAX_EPISODE) + '\n\tStep: ' + str(int(epi_step_stack[v])) )
            print('\tEpisode Reward: ' + str(epi_reward_stack[v])) 
            print('Last Loss: ',data_package.avg_loss[-1])
            print('========')
            print('')

        # Update Counters
        epi_step_stack = epi_step_stack + 1

        # Reset rewards for finished vehicles
        for v in reset_veh_list:
            data_package.add_reward( epi_reward_stack[v] )  # Add reward
            data_package.add_eps( eps )                     # Add epsilon used for this reward

            epi_reward_stack[v] = 0
            epi_step_stack[v] = 0

        # save progress
        if options.TESTING == False:
            if options.NO_SAVE == False and epi_counter - last_saved_epi >= options.SAVER_RATE:
                print('-----------------------------------------')
                print("Saving network...")
                print('-----------------------------------------')
                saver.save(sess, 'checkpoints-vehicle/vehicle-dqn_s' + START_TIME_STR + "_e" + str(epi_counter) + "_gs" + str(global_step))
                #print("Done") 

                print('-----------------------------------------')
                print("Saving data...") 
                print('-----------------------------------------')

                # Save Reward Data
                data_package.save_reward()
                data_package.save_loss()

                # Update variables
                last_saved_epi = epi_counter


        # GS_END_TIME_STR   = datetime.datetime.now()
        # print('Time : ' + str(GS_END_TIME_STR - GS_START_TIME_STR))

    # stop the simulation & close connection
    p.disconnect()

    ######################################################
    # Post Processing
    ######################################################

    # Print Current Time
    END_TIME = datetime.datetime.now()
    print("===============================")
    print("Start Time: ",START_TIME_STR)
    print("End Time  : ",str(END_TIME).replace(" ","_"))
    print("Duration  : ",END_TIME-START_TIME)
    print("===============================")

    #############################3
    # Visualize Data
    ##############################3

    # Plot Reward
    data_package.plot_reward( options.RUNNING_AVG_STEP )
    data_package.plot_loss()


# END
