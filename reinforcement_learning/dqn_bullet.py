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

from utils.env_py import *
from utils.experience_replay import Memory, SumTree
from utils.rl_dqn import QAgent
from utils.rl_icm import ICM
from utils.scene_constants_pb import scene_constants
from utils.utils_data import data_pack
from utils.utils_pb import (controlCamera, detectCollision, detectReachedGoal,
                            drawDebugLines, getObs, initQueue, resetQueue)


def get_options():
    # Parser Settings
    parser = ArgumentParser(
        description='File for learning'
        )
    parser.add_argument('--MAX_EPISODE', type=int, default=10000,
                        help='max number of episodes iteration\n')
    parser.add_argument('--MAX_TIMESTEP', type=int, default=200,
                        help='max number of time step of simulation per episode')
    parser.add_argument('--ACTION_DIM', type=int, default=5,
                        help='number of actions one can take')
    parser.add_argument('--OBSERVATION_DIM', type=int, default=11,
                        help='number of observations one can see')
    parser.add_argument('--GAMMA', type=float, default=0.995,
                        help='discount factor of Q learning')
    parser.add_argument('--INIT_EPS', type=float, default=1.0,
                        help='initial probability for randomly sampling action')
    parser.add_argument('--FINAL_EPS', type=float, default=1e-1,
                        help='finial probability for randomly sampling action')
    parser.add_argument('--EPS_DECAY', type=float, default=0.995,
                        help='epsilon decay rate')
    parser.add_argument('--EPS_ANNEAL_STEPS', type=int, default=1800,
                        help='steps interval to decay epsilon')
    parser.add_argument('--LR', type=float, default=1e-4,
                        help='learning rate')
    parser.add_argument('--MAX_EXPERIENCE', type=int, default=10000,
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
                        help='Enable the GUI.'),
    parser.add_argument('--VERBOSE', action='store_true', default = False,
                        help='Verbose output')
    parser.add_argument('--disable_duel', action='store_true',
                        help='Disable the usage of double network.')
    parser.add_argument('--FRAME_COUNT', type=int, default=1,
                        help='Number of frames to be used')
    parser.add_argument('--ACT_FUNC', type=str, default='relu',
                        help='Activation function')
    parser.add_argument('--GOAL_REW', type=int, default=6000,
                        help='Activation function')
    parser.add_argument('--FAIL_REW', type=int, default=-2000,
                        help='Activation function')
    parser.add_argument('--VEH_COUNT', type=int, default=6,
                        help='Number of vehicles to use for simulation')
    parser.add_argument('--INIT_SPD', type=int, default=15,
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
    parser.add_argument('--FIX_INPUT_STEP', type=int, default=6,
                        help='Fix input steps')
    parser.add_argument('--X_COUNT', type=int, default=6,
                        help='Width of the grid for vehicles. Default of 5 means we lay down 5 vehicles as the width of the grid')
    parser.add_argument('--THREAD', type=int, default=1,
                        help='Number of threads for parallel simulation.')
    parser.add_argument('--WEIGHT_FILE', type=str, default=None,
                        help='Relative path to the weight file to load. Only works for KERAS.')
    options = parser.parse_args()

    # Check Inputs
    if options.TARGET_UPDATE_STEP % options.VEH_COUNT != 0:
        raise ValueError('VEH_COUNT must divide TARGET_UPDATE_STEPS')

    if options.EPS_ANNEAL_STEPS % options.VEH_COUNT != 0:
        raise ValueError('VEH_COUNT must divide EPS_ANNEAL_STEPS')

    # Save options
    if not os.path.exists("./checkpoints-vehicle"):
        os.makedirs("./checkpoints-vehicle")

    if options.TESTING == True:
        option_file = open("./checkpoints-vehicle/options_TESTING_"+START_TIME_STR+'.txt', "w")
    else:
        option_file = open("./checkpoints-vehicle/options_"+START_TIME_STR+'.txt', "w")

    # For each option
    for x in sorted(vars(options).keys()):
        # Option string
        opt_str = str(x).ljust(20) + ": " + str(vars(options)[x]).ljust(10)
        if vars(options)[x] == parser.get_default(x):
            opt_str = opt_str + '(DEFAULT)'

        # Print to file
        option_file.write( opt_str )   # write option
        option_file.write('\n')

        # Print to terminal
        print( opt_str )
    option_file.close()

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

def saveNetworkKeras():
    print('-----------------------------------------')
    print("Saving network...")
    print('-----------------------------------------')
    if not os.path.exists('./checkpoints-vehicle'):
        os.makedirs('./checkpoints-vehicle')
    agent_train.model.save_weights('./checkpoints-vehicle/' + START_TIME_STR + "_e" + str(epi_counter) + "_gs" + str(global_step) + '.h5', overwrite=True)

    # Save checkpoint
    with open('./checkpoints-vehicle/checkpoint.txt','w') as check_file:
        check_file.write(START_TIME_STR + "_e" + str(epi_counter) + "_gs" + str(global_step) + '.h5')

    return

def loadNetworkKeras():
    weight_path = None

    # If file is provided
    if options.WEIGHT_FILE != None:
        weight_path = options.WEIGHT_FILE
    elif os.path.isfile('./checkpoints-vehicle/checkpoint.txt'):
        with open('./checkpoints-vehicle/checkpoint.txt') as check_file:
            weight_file = check_file.readline()
            weight_path = './checkpoints-vehicle/' + weight_file 

    if weight_path == None:
        print("\n\n=================================================")
        print("=================================================")
        print("Could not find old network weights")
        print("=================================================")
        print("=================================================\n\n")
    else:
        agent_train.model.load_weights( weight_path )
        agent_target.model.load_weights( weight_path )
        print("\n\n=================================================")
        print("=================================================")
        print("Successfully loaded:", weight_path)
        print("=================================================")
        print("=================================================\n\n")

    return

########################
# MAIN
########################
if __name__ == "__main__":
    print('=================VERSION==============================')
    print('TENSOR FLOW VERSION : ' + tf.VERSION)
    print('KERAS VERSION       : ' + tf.keras.__version__)
    print('PYTHON VERSION      : ' + sys.version)
    print('=================OPTIONS==============================')

    # SET 'GLOBAL' Variables
    START_TIME       = datetime.datetime.now()
    START_TIME_STR   = re.sub( r'\ |:', '_', str( START_TIME) )

    # Parse options
    _, options = get_options()

    ########
    # Set Seed
    ########
    np.random.seed( options.SEED )
    random.seed( options.SEED )
    tf.set_random_seed( options.SEED )

    # Set print options
    np.set_printoptions( precision = 4, linewidth = 100 )

    # For interactive plot
    plt.ion()

    ######################################
    # Simulation Start
    ######################################
    # Randomize obstacle position at initScene
    RANDOMIZE = True

    # Initial Camera position
    cam_pos = [0,0,0]
    cam_dist = 5

    # Start Environment
    sim_env                                     = env_py( options, scene_constants() )
    sim_env.scene_const.clientID, handle_dict   = sim_env.start()

    # Print Infos
    sim_env.printInfo()

    # Draw initial lines
    if options.enable_GUI == True:
        sensor_handle = drawDebugLines( options, sim_env.scene_const, handle_dict, createInit = True )
        collision_handle = drawDebugLines( options, sim_env.scene_const, handle_dict, createInit = True )

    # Print Handles
    ic(handle_dict)

    ##############
    # TF Setup
    ##############
    # Define placeholders to catch inputs and add options
    agent_train     = QAgent(options,sim_env.scene_const, 'Training')
    agent_target    = QAgent(options,sim_env.scene_const, 'Target')
    agent_icm       = ICM(options,sim_env.scene_const,'icm_Training')

    # saving and loading networks
    if options.NO_SAVE == False:
        loadNetworkKeras()
    
    # Some initial local variables
    feed            = {}
    feed_icm        = {}
    global_step     = 0

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
            # np.savetxt( './model_weights/' + fixed_name + '.txt', sess.run([v])[0], delimiter=',')
        sys.exit() 


    ########################
    # END TF SETUP
    ########################

    ###########################        
    # DATA VARIABLES
    ###########################        
    data_package = data_pack( START_TIME_STR )    

    ###########################        
    # Initialize Variables
    ###########################        
   
    # Some variables
    action_stack        = np.zeros(options.VEH_COUNT)                              # action_stack[k] is the array of optinos.ACTION_DIM with each element representing the index
    epi_counter         = 0                                                        # Counts # of finished episodes
    eps_tracker         = np.zeros(options.MAX_EPISODE+options.VEH_COUNT+1)
    last_saved_epi      = 0                                                             # variable used for checking when to save
    case_direction      = np.zeros(options.VEH_COUNT)                               # store tested direction

    # Initialize Scene
    _, _, _ = sim_env.initScene( list(range(0,options.VEH_COUNT)), False )

    # List of deque to store data
    sensor_queue = []
    goal_queue   = []
    for i in range(0,options.VEH_COUNT):
        sensor_queue.append( deque() )
        goal_queue.append( deque() )

    # initilize them with initial data
    _, _, dDistance, gInfo   = sim_env.getObservation()
    sensor_queue, goal_queue = initQueue( options, sensor_queue, goal_queue, dDistance, gInfo )

    # Global Step Loop
    while epi_counter <= options.MAX_EPISODE:
        # GS_START_TIME_STR   = datetime.datetime.now()
        if options.enable_GUI == True and options.manual == False:
            cam_pos, cam_dist = controlCamera( cam_pos, cam_dist )  
            time.sleep(0.01)

        # Decay epsilon
        agent_train.decayEps( options, global_step )
        global_step += options.VEH_COUNT

        ####
        # Find & Apply Action
        ####
        obs_sensor_stack = np.empty((options.VEH_COUNT, sim_env.scene_const.sensor_count, options.FRAME_COUNT))
        obs_goal_stack   = np.empty((options.VEH_COUNT, 2, options.FRAME_COUNT))

        # Get observation stack (which is used in getting the action) 
        for v in range(0,options.VEH_COUNT):
            # Get current info to generate input
            obs_sensor_stack[v], obs_goal_stack[v]   = getObs( options, sim_env.scene_const, sensor_queue[v], goal_queue[v], old=False)

        # ic(obs_sensor_stack)
        # ic(obs_goal_stack)
        # Get optimal action TF. 
        # action_stack = agent_train.sample_action(
        #                                     {
        #                                         agent_train.obs_sensor : obs_sensor_stack,
        #                                         agent_train.obs_goal   : obs_goal_stack
        #                                     },
        #                                     options,
        #                                     )

        # Get optimal action Keras. 
        action_stack_k = agent_train.sample_action_k(
                                            {
                                                'observation_sensor_k' : obs_sensor_stack,
                                                'observation_goal_k'   : obs_goal_stack
                                            },
                                            options,
                                            )

        # Apply the Steering Action & Keep Velocity. For some reason, +ve means left, -ve means right
        # targetSteer = sim_env.scene_const.max_steer - action_stack * abs(sim_env.scene_const.max_steer - sim_env.scene_const.min_steer)/(options.ACTION_DIM-1)
        targetSteer_k = sim_env.scene_const.max_steer - action_stack_k * abs(sim_env.scene_const.max_steer - sim_env.scene_const.min_steer)/(options.ACTION_DIM-1)

        # ic(action_stack)
        # ic(targetSteer)
        #steeringSlider = p.addUserDebugParameter("steering", -2, 2, 0)
        #steeringAngle = p.readUserDebugParameter(steeringSlider)
        sim_env.applyAction( targetSteer_k )

        ####
        # Step
        ####
        sim_env.step()

        ####
        # Get Next State
        ####
        next_veh_pos, next_veh_heading, next_dDistance, next_gInfo = sim_env.getObservation( verbosity = options.VERBOSE )
        # print(next_dDistance)

        for v in range(0,options.VEH_COUNT):
            # Update queue
            sensor_queue[v].append(next_dDistance[v])
            sensor_queue[v].popleft()
            goal_queue[v].append(next_gInfo[v])
            goal_queue[v].popleft()

        ####
        # Handle Events & Get Rewards
        ####
        reward_stack, veh_status, epi_done, epi_sucess = sim_env.getRewards( next_dDistance, next_veh_pos, next_gInfo, next_veh_heading)

        # List of resetting vehicles
        reset_veh_list = [ v for v in range(0,options.VEH_COUNT) if veh_status[v] != sim_env.scene_const.EVENT_FINE ]

        # Update epi counter
        epi_counter += len(reset_veh_list)

        if options.VERBOSE == True:
            ic(reward_stack)

        # Draw Debug Lines
        if options.enable_GUI == True:
            # Draw Lidar
            sensor_handle = drawDebugLines(options, sim_env.scene_const, handle_dict, next_dDistance, sensor_handle, createInit = False )

            # Draw Collision Range
            collision_handle = drawDebugLines(options, sim_env.scene_const, handle_dict, np.ones((options.VEH_COUNT,sim_env.scene_const.sensor_count))*(sim_env.scene_const.collision_distance/sim_env.scene_const.sensor_distance), collision_handle, createInit = False, ray_width = 4, rayHitColor = [0,0,0] )

        #######
        # Test Estimation
        #######
        if options.TESTING == True:
            v = 0

            # Print curr & next state
            curr_state_sensor, curr_state_goal     = getObs( options, sim_env.scene_const, sensor_queue[v], goal_queue[v], old=True)
            next_state_sensor, next_state_Goal     = getObs( options, sim_env.scene_const, sensor_queue[v], goal_queue[v], old=False)
            #print('curr_state:', curr_state)
            #print('next_state:', next_state)
            #print('estimate  :', agent_icm.getEstimate( {agent_icm.observation : np.reshape(np.concatenate([curr_state, action_stack[v]]), [-1, 16])  }  ) )
            #print('')
            # agent_icm.plotEstimate( sim_env.scene_const, options, curr_state, action_stack[v], next_veh_heading[v], agent_train, save=True, ref = 'vehicle')

        ###########
        # START LEARNING
        ###########

        # Add latest information to memory
        for v in range(0,options.VEH_COUNT):
            # Get observation
            observation_sensor, observation_goal             = getObs( options, sim_env.scene_const, sensor_queue[v], goal_queue[v], old = True)
            next_observation_sensor, next_observation_goal   = getObs( options, sim_env.scene_const, sensor_queue[v], goal_queue[v], old = False)

            # Add experience. (observation, action in one hot encoding, reward, next observation, done(1/0) )
            experience = observation_sensor, observation_goal, action_stack_k[v], reward_stack[v], next_observation_sensor, next_observation_goal, epi_done[v]
           
            # Save new memory 
            replay_memory.store(experience)

        # Start training
        if global_step >= options.MAX_EXPERIENCE and options.TESTING == False:
            for tf_train_counter in range(0,options.VEH_COUNT):
                # Obtain the mini batch. (Batch Memory is '2D array' with BATCH_SIZE X size(experience)
                tree_idx, batch_memory, ISWeights_mb = replay_memory.sample(options.BATCH_SIZE)

                # Get state/action/next state from obtained memory. Size same as queues
                states_sensor_mb        = np.array([each[0][0] for each in batch_memory])           # BATCH_SIZE x SENSOR_COUNT
                states_goal_mb          = np.array([each[0][1] for each in batch_memory])           # BATCH_SIZE x 2
                actions_mb              = np.array([each[0][2] for each in batch_memory])           # BATCH_SIZE x ACTION_DIM
                rewards_mb              = np.array([each[0][3] for each in batch_memory])           # 1 x BATCH_SIZE
                next_states_sensor_mb   = np.array([each[0][4] for each in batch_memory])   
                next_states_goal_mb     = np.array([each[0][5] for each in batch_memory])   
                done_mb                 = np.array([each[0][6] for each in batch_memory])   

                # actions mb is list of numbers. Need to change it into one hot encoding
                actions_mb_hot = np.zeros((options.BATCH_SIZE,options.ACTION_DIM))
                actions_mb_hot[np.arange(options.BATCH_SIZE),np.asarray(actions_mb, dtype=int)] = 1

                # actions converted to value array
                #actions_mb_val = oneHot2Angle( actions_mb_hot, sim_env.scene_const, options, radians = False, scale = True )

                # ic(states_mb,actions_mb,rewards_mb,next_states_mb,done_mb)
                # ic( next_states_mb.reshape(-1,sim_env.scene_const.sensor_count+2,options.FRAME_COUNT) )

                # Get Target Q-Value
                # feed.clear()
                # feed.update({agent_train.obs_sensor : next_states_sensor_mb, agent_train.obs_goal : next_states_goal_mb})

                # Calculate Target Q-value. Uses double network. First, get action from training network
                # action_train = np.argmax( agent_train.output.eval(feed_dict=feed), axis=1 )
                action_train_k = agent_train.model_out.predict(
                                                    {
                                                        'observation_sensor_k' : next_states_sensor_mb,
                                                        'observation_goal_k'   : next_states_goal_mb
                                                    },
                                                    batch_size = options.VEH_COUNT
                )
                action_train_k = np.argmax( action_train_k, axis=1)
                # ic(np.argmax(action_train_k,axis=1))

                if options.disable_DN == False:
                    # feed.clear()
                    # feed.update({agent_target.obs_sensor : next_states_sensor_mb, agent_target.obs_goal : next_states_goal_mb})

                    keras_feed = {}
                    keras_feed.clear()
                    keras_feed.update(
                        {
                            'observation_sensor_k' : next_states_sensor_mb,
                            'observation_goal_k'   : next_states_goal_mb
                        }

                    )
                    # Using Target + Double network
                    # ic( agent_target.output.eval( feed_dict = feed), agent_target.output.eval( feed_dict = feed).shape  )
                    # ic( agent_target.h_s1.eval( feed_dict = feed), agent_target.h_s1.eval( feed_dict = feed).shape  )
                    # ic( agent_target.output.eval(feed_dict=feed)[np.arange(0,options.BATCH_SIZE),action_train] )
                    # q_target_val = rewards_mb + options.GAMMA * agent_target.output.eval(feed_dict=feed)[np.arange(0,options.BATCH_SIZE),action_train]
                    q_target_val_k = rewards_mb + options.GAMMA * agent_target.model_out.predict(keras_feed)[np.arange(0,options.BATCH_SIZE),action_train_k]
                else:
                    # feed.clear()
                    # feed.update({agent_target.obs_sensor : next_states_sensor_mb, agent_target.obs_goal : next_states_goal_mb})

                    keras_feed.clear()
                    keras_feed.update(
                        {
                            'observation_sensor_k' : next_states_sensor_mb,
                            'observation_goal_k'   : next_states_goal_mb
                        }

                    )
                    # Just using Target Network.
                    q_target_val = rewards_mb + options.GAMMA * np.amax( agent_target.output.eval(feed_dict=feed), axis=1)
                    q_target_val_k = rewards_mb + options.GAMMA * np.amas( agent_target.model.predict(keras_feed), axis=1)
           
                # set q_target to reward if episode is done
                for v_mb in range(0,options.BATCH_SIZE):
                    if done_mb[v_mb] == 1:
                        # q_target_val[v_mb] = rewards_mb[v_mb]
                        q_target_val_k[v_mb] = rewards_mb[v_mb]

                #print('q_target_val', q_target_val) 
                #print("\n\n")
                # ic(q_target_val, q_target_val_k)

                # Gradient Descent
                # feed.clear()
                # feed.update({agent_train.obs_sensor : states_sensor_mb, agent_train.obs_goal : states_goal_mb})
                # feed.update({agent_train.act : actions_mb_hot})
                # feed.update({agent_train.target_Q : q_target_val } )        # Add target_y to feed
                # feed.update({agent_train.ISWeights : ISWeights_mb   })

                #with tf.variable_scope("Training"):   
                # Train RL         
                # step_loss_per_data, step_loss_value, _  = sess.run([agent_train.loss_per_data, agent_train.loss, agent_train.optimizer], feed_dict = feed)

                # Train Keras Model
                keras_feed = {}
                keras_feed.clear()
                keras_feed.update({ 'observation_sensor_k' : states_sensor_mb, 'observation_goal_k' : states_goal_mb})
                # ic(keras_feed['observation_sensor_k'].shape)
                # ic(keras_feed['observation_goal_k'].shape)
                # ic(q_target_val.shape)
                # ic( agent_train.model_out.predict( keras_feed ) )
                # q_target_val_k = np.ones((options.BATCH_SIZE,1))
                loss_k = agent_train.model.train_on_batch( keras_feed, np.reshape(q_target_val_k,(options.BATCH_SIZE,1)) )

                ##############################
                # Train forward model
                ##############################
                feed_icm.clear()

                # Feed
                feed_icm.update(
                    { 
                        'icm_input_sensor_frame' : states_sensor_mb,
                        'icm_input_action'       : actions_mb*(1/(options.ACTION_DIM-1)),         # action_stack is 0 to ACTION_DIM, scale to 0-1
                    }
                )

                # next_statse have BATCH_SIZE x SENSOR_COUNT x FRAME_COUNT. Hence, [:,:,-1] pick up the latest frame
                icm_target = np.hstack([next_states_sensor_mb[:,:,-1], next_states_goal_mb[:,:,-1]])

                # Train
                loss_icm_k = agent_icm.model.train_on_batch( feed_icm, icm_target )



                # Save LOSS
                data_package.add_loss( loss_k )

                # Update priority
                # replay_memory.batch_update(tree_idx)
        elif global_step < options.MAX_EXPERIENCE:
            # If just running to get memory, do not increment counter
            epi_counter = 0

        handle_dict, sim_env.scene_const, case_direction = sim_env.initScene( reset_veh_list, RANDOMIZE )

        # Reset data queue
        _, _, reset_dDistance, reset_gInfo = sim_env.getObservation()
        sensor_queue, goal_queue = resetQueue( options, sensor_queue, goal_queue, reset_dDistance, reset_gInfo, reset_veh_list )

        ###############
        # Miscellaneous
        ###############
        # Update Target
        if global_step % options.TARGET_UPDATE_STEP == 0:
            print('-----------------------------------------')
            print("Updating Target network.")
            print('-----------------------------------------')
            # copy_online_to_target.run()
            agent_target.model.set_weights( agent_train.model.get_weights() )

        # Print Rewards
        for v in reset_veh_list:
            print('========')
            print('Vehicle #:', v)
            print('\tGlobal Step:' + str(global_step))
            print('\tEPS: ' + str(agent_train.eps))
            print('\tEpisode #: ' + str(epi_counter) + ' / ' + str(options.MAX_EPISODE) + '\n\tStep: ' + str(int(sim_env.epi_step_stack[v])) )
            print('\tEpisode Reward: ' + str(sim_env.epi_reward_stack[v])) 
            print('\tDirection: ' + str(case_direction[v]) ) 
            print('Last Loss: ',data_package.avg_loss[-1])
            print('========')
            print('')

        # Update data
        for v in reset_veh_list:
            data_package.add_reward( sim_env.epi_reward_stack[v] )  # Add reward
            data_package.add_eps( agent_train.eps )                     # Add epsilon used for this reward
            data_package.add_success_rate( epi_sucess[v] )  # Add success/fail

        # Reset rewards for finished vehicles
        sim_env.resetRewards(veh_status)

        # save progress
        if options.TESTING == False:
            if options.NO_SAVE == False and epi_counter - last_saved_epi >= options.SAVER_RATE:
                saveNetworkKeras()
                # print('-----------------------------------------')
                # print("Saving network...")
                # print('-----------------------------------------')
                # saver.save(sess, 'checkpoints-vehicle/vehicle-dqn_s' + START_TIME_STR + "_e" + str(epi_counter) + "_gs" + str(global_step))
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
    sim_env.end()

    ######################################################
    # Post Processing
    ######################################################

    # Print Current Time
    END_TIME = datetime.datetime.now()
    print("===============================")
    print("Start Time: ",START_TIME_STR)
    print("End Time  : ",str(END_TIME))
    print("Duration  : ",END_TIME-START_TIME)
    print("===============================")

    #############################3
    # Visualize Data
    ##############################3

    # Plot Reward
    data_package.plot_reward( options.RUNNING_AVG_STEP )
    data_package.plot_loss()


# END
