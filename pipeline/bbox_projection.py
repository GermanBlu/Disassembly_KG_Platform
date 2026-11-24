"""Bounding-box projection for the interference check.

Projects the corners of each part's bounding box into a coordinate system whose
third axis is the test direction. The first two coordinates give the footprint
on the plane perpendicular to the direction, the third gives the depth interval
along it. pipeline.interference uses both to select candidate blockers before
the occlusion test (preprocessing stage of Prasad et al., 2022).
"""
import numpy as np
from OCC.Core.gp import gp_Dir

from pipeline.part import Part


##define transformation matrix
#dimensions: points:array of m points where each point is of dimension 1*n -> m x n matrix
def calculate_transformation_matrix(direction: gp_Dir):
    ## v1 and v2 define plane perpendicular to direction, direction already normalized as member of gp_Dir()
    direction_arr = np.array([direction.X(), direction.Y(), direction.Z()])
    if np.dot(direction_arr, np.array([1,0,0])) != 1 and np.dot(direction_arr, np.array([1,0,0])) != -1:
        v1 = np.array([1,0,0])
    else: v1 = np.array([(0,1,0)])
    v1 = v1 - (np.dot(v1, direction_arr) *direction_arr)
    v2 = np.cross(direction_arr, v1)
    
    ## matrix with v1, v2, direction_arr as basis vectors 
    matrix = np.zeros((3,3))
    matrix[:, 0] = v1
    matrix[:, 1] = v2
    matrix[:, 2] = direction_arr

    transform_matrix = np.linalg.inv(matrix)
    return transform_matrix

## Calculate the missing points of the bounding boxes
## This is necessary to project the Bboxes to 2D plane in the function project_to_plane
## corners_Bbox = [lower_left_back_corner, lower_right_back_corner, upper_left_back_corner, upper_right_back_corner, ... same for front ]
## left -> right: x-axis
## front -> back: y-axis
## lower -> upper: z-axis
def calc_other_Bbox_points(parts: list[Part]):
    for part in parts:
        x_min, y_min, z_min, x_max, y_max, z_max = part.BoundingBox.Get()
        ## points in back
        part.corners_Bbox.append(np.array([x_min, y_min, z_min]))
        part.corners_Bbox.append(np.array([x_max, y_min, z_min]))
        part.corners_Bbox.append(np.array([x_min, y_min, z_max]))
        part.corners_Bbox.append(np.array([x_max, y_min, z_max]))
        ## points in front
        part.corners_Bbox.append(np.array([x_min, y_max, z_min]))
        part.corners_Bbox.append(np.array([x_max, y_max, z_min]))
        part.corners_Bbox.append(np.array([x_min, y_max, z_max]))
        part.corners_Bbox.append(np.array([x_max, y_max, z_max]))
    return parts
    

# This function aims at projecting the points defining the bounding boxes of the parts to the coordinate system spanned by u,v defining the plane and normal (w) perpendicular to v1&v2
def project_to_plane(parts: list[Part], transformation_matrix):
    for part in parts:
        u_coords = []
        v_coords = []
        w_coords = []
        for corner in part.corners_Bbox:
            transformed_corner = transformation_matrix @ corner
            part.transformed_corners.append(transformed_corner)
            u_coords.append(transformed_corner[0])
            v_coords.append(transformed_corner[1])
            w_coords.append(transformed_corner[2])
        part.p_min = np.array([min(u_coords), min(v_coords)])
        part.p_max = np.array([max(u_coords), max(v_coords)])
        ## designate max w- value as depth of part (depth in disassembly direction) !!!!!!!!
        part.depth_intervall = [min(w_coords), max(w_coords)]
        
    return parts
