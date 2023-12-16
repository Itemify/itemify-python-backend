import json
from kafka import KafkaConsumer
from mpl_toolkits import mplot3d
from matplotlib import pyplot
from matplotlib.colors import LightSource
import numpy
from stl import mesh
import os

consumer = KafkaConsumer(os.getenv("KAFKA_TOPIC"),
                         group_id=os.getenv("KAFKA_GROUP_ID"),
                         value_deserializer=lambda m: json.loads(m.decode('ascii')),
                         bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS").split(","))


def plotSTLToPNG(filename):
    # Create a new plot
    figure = pyplot.figure(figsize=(20, 20))
    axes = figure.add_subplot(111, projection='3d')

    # Load the STL mesh
    stlmesh = mesh.Mesh.from_file(filename)
    polymesh = mplot3d.art3d.Poly3DCollection(stlmesh.vectors)

    # Create light source
    ls = LightSource(azdeg=225, altdeg=45)

    # Darkest shadowed surface, in rgba
    dk = numpy.array([66 / 255, 4 / 255, 126 / 255, 1])
    # Brightest lit surface, in rgba
    lt = numpy.array([7 / 255, 244 / 255, 158 / 255, 1])
    # Interpolate between the two, based on face normal
    shade = lambda s: (lt - dk) * s + dk

    # Set face colors
    sns = ls.shade_normals(stlmesh.get_unit_normals(), fraction=1.0)
    rgba = numpy.array([shade(s) for s in sns])
    polymesh.set_facecolor(rgba)

    axes.add_collection3d(polymesh)

    # Adjust limits of axes to fill the mesh, but keep 1:1:1 aspect ratio
    pts = stlmesh.points.reshape(-1, 3)
    ptp = max(numpy.ptp(pts, 0)) / 2
    ctrs = [(min(pts[:, i]) + max(pts[:, i])) / 2 for i in range(3)]
    lims = [[ctrs[i] - ptp, ctrs[i] + ptp] for i in range(3)]
    axes.auto_scale_xyz(*lims)
    axes.set_axis_off()

    pyplot.savefig(filename + ".png", bbox_inches='tight')


for message in consumer:
    print("%s:%d:%d: key=%s value=%s" % (message.topic, message.partition,
                                         message.offset, message.key,
                                         message.value))

    plotSTLToPNG(message.value['item_file']['file_path'])
