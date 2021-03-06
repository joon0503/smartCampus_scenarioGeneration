#######
# This is class containing all constants relevant to the test scene for bullet simulation

import math

import numpy as np


class scene_constants:

    # Maximum distance for sensor readings
    sensor_distance     = 10
    max_distance        = sensor_distance        # DEPRECATED

    # Number of sensors
    sensor_count        = 19

    # Sensor Range in Radians
    #   0 -> front
    #   +\pi/2 -> right
    #   -\pi -> left
    sensor_max_angle    = math.pi/2
    sensor_min_angle    = -math.pi/2

    # Angle (in radians) difference between each radar sensor
    sensor_delta = (sensor_max_angle - sensor_min_angle) / (sensor_count - 1)

    # Define rayTo and rayFrom. Each are 2d arrays
    rayTo       = []
    rayFrom     = []
    i           = 0
    curr_angle  = 0
    for i in range (sensor_count):
        # Reference is : y-axis for horizontal, +ve is left.   x-axis for vertical, +ve is up
        curr_angle = sensor_max_angle - i*sensor_delta
        rayFrom.append([0,0,0])
        rayTo.append([sensor_distance*np.cos( curr_angle ), sensor_distance * np.sin( curr_angle ), 0])


    # Contant that scales the angles (i.e., goal point angle)
    angle_scale = math.pi/2
 
    # client ID
    clientID            = []

    # Maximum steering angle in degrees
    max_steer           = 15
    min_steer           = -1*max_steer

    # Collision occurs if readings are less than this number. in meters
    collision_distance  = 1.0   # this means if sensor is 0.1, then collision

    # Distance to the goal. Used for normalization
    goal_distance       = 40
    detect_range        = 1.0

    # Simulation Parameters
    # dt = 0.025                      # dt of the vrep simulation

    # Test Case related
    obs_w           = (3/8)         # obstacle width ratio
    lane_width      = 2             # lane width
    lane_len        = 50            # total len
    turn_len        = 30            # total len after tun
    case_x          = 50            # distance between each case
    case_y          = 150            # distance between each case
    veh_init_y      = 0            # initial vehicle y position
    wall_cnt        = 9             # number of walls
    wall_h          = 1.5           # height of walls

    MIN_X_POS       = 0             # Minimum x-pos at start
    MAX_X_POS       = 0             # Maximum x-pos at start

    MIN_LANE_WIDTH  = 4.0           # Min / Max width of test case
    MAX_LANE_WIDTH  = 8.0

    # y-axis distance where obstacle lies
    MAX_OBS_Y_POS   = lane_len * 0.5 * 0.75         
    MIN_OBS_Y_POS   = lane_len * 0.5 * 0.25

    # Initial y-axis position 
    MIN_Y_INIT      = 0 
    MAX_Y_INIT      = lane_len * 0.5 * 0.25

    # Enable obstacle at Left/Middle/Right
    OBS_ENABLE      = [1,0,1]

    # Scaling
    veh_scale       = 2.0           # vehicle scale

    ####
    # Curriculum Learniung related parameters
    ####




    # Contants for Event Handling
    EVENT_FINE          = 0
    EVENT_COLLISION     = 1
    EVENT_GOAL          = 2
    EVENT_OVER_MAX_STEP = 3
