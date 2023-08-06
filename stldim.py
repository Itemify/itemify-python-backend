#!/usr/bin/python3

# Python script to find STL dimensions
# Requrements: sudo pip install numpy-stl

import math
import stl
from stl import mesh
import numpy

import os
import sys

# this stolen from numpy-stl documentation
# https://pypi.python.org/pypi/numpy-stl

# find the max dimensions, so we can know the bounding box, getting the height,
# width, length (because these are the step size)...
def find_mins_maxs(obj):
    minx = maxx = miny = maxy = minz = maxz = None
    for p in obj.points:
        # p contains (x, y, z)
        if minx is None:
            minx = p[stl.Dimension.X]
            maxx = p[stl.Dimension.X]
            miny = p[stl.Dimension.Y]
            maxy = p[stl.Dimension.Y]
            minz = p[stl.Dimension.Z]
            maxz = p[stl.Dimension.Z]
        else:
            maxx = max(p[stl.Dimension.X], maxx)
            minx = min(p[stl.Dimension.X], minx)
            maxy = max(p[stl.Dimension.Y], maxy)
            miny = min(p[stl.Dimension.Y], miny)
            maxz = max(p[stl.Dimension.Z], maxz)
            minz = min(p[stl.Dimension.Z], minz)
    return minx, maxx, miny, maxy, minz, maxz

def get_dimensions(file):
    print(file)
    main_body = mesh.Mesh.from_file(file)
    
    minx, maxx, miny, maxy, minz, maxz = find_mins_maxs(main_body)
    
    return (maxx - minx, maxy - miny, maxz - minz)


# the logic is easy from there
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: %s [stl file]' % sys.argv[0])

    if not os.path.exists(sys.argv[1]):
        sys.exit('ERROR: file %s was not found!' % sys.argv[1])
        
    x, y, z = get_dimensions(sys.argv[1])
    
    print("File:", sys.argv[1])
    print("X:", x) 
    print("Y:", y) 
    print("Z:", z) 
