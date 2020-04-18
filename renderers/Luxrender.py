# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2017 Yorik van Havre <yorik@uncreated.net>              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""Luxrender renderer for FreeCAD"""

# This file can also be used as a template to add more rendering engines.
# You will need to make sure your file is named with a same name (case
# sensitive)
# That you will use everywhere to describe your renderer, ex: Appleseed or
# Povray


# A render engine module must contain the following functions:
#
# write_camera(pos, rot, up, target)
#   returns a string containing an openInventor camera string in renderer
#   format
#
# write_object(view, mesh, color, alpha)
#   returns a string containing a RaytracingView object in renderer format
#
# render(project, prefix, external, output, width, height)
#   renders the given project
#   external means if the user wishes to open the render file in an external
#   application/editor or not. If this is not supported by your renderer, you
#   can simply ignore it
#
# Additionally, you might need/want to add:
#   Preference page items, that can be used in your functions below
#   An icon under the name Renderer.svg (where Renderer is the name of your
#   Renderer


import os
import re
import shlex
from tempfile import mkstemp
from subprocess import Popen
from textwrap import dedent

import FreeCAD as App


def write_camera(pos, rot, updir, target, name):
    """Compute a string in the format of Luxrender, that represents a camera"""
    # This is where you create a piece of text in the format of
    # your renderer, that represents the camera.

    snippet = """
    # Generated by FreeCAD (http://www.freecadweb.org/)
    # Declares position and view direction (camera '{0}')
    LookAt   {1.x} {1.y} {1.z}   {2.x} {2.y} {2.z}   {3.x} {3.y} {3.z}
    \n"""

    return dedent(snippet).format(name, pos, target, updir)


def write_object(viewobj, mesh, color, alpha):
    """Compute a string in the format of Luxrender, that represents a FreeCAD
    object
    """
    # This is where you write your object/view in the format of your
    # renderer. "obj" is the real 3D object handled by this project, not
    # the project itself. This is your only opportunity
    # to write all the data needed by your object (geometry, materials, etc)
    # so make sure you include everything that is needed

    points = ["{0.x} {0.y} {0.z}".format(v) for v in mesh.Topology[0]]
    norms = ["{0.x} {0.y} {0.z}".format(n) for n in mesh.getPointNormals()]
    tris = ["{} {} {}".format(*t) for t in mesh.Topology[1]]

    snippet = """
    # Generated by FreeCAD (http://www.freecadweb.org/)
    MakeNamedMaterial "{name}_mat"
        "color Kd"              [{colo[0]} {colo[1]} {colo[2]}]
        "float sigma"           [0.2]
        "string type"           ["matte"]
        "float transparency"    [{trsp}]

    AttributeBegin  # {name}
    Transform [1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1]
    NamedMaterial "{name}_mat"
    Shape "mesh"
        "integer triindices" [{inds}]
        "point P" [{pnts}]
        "normal N" [{nrms}]
        "bool generatetangents" ["false"]
        "string name" ["{name}"]
    AttributeEnd  # {name}
    """

    return dedent(snippet).format(name=viewobj.Name,
                                  colo=color,
                                  trsp=alpha if alpha < 1.0 else 1.0,
                                  inds=" ".join(tris),
                                  pnts=" ".join(points),
                                  nrms=" ".join(norms))


def write_pointlight(view, location, color, power):
    """Compute a string in the format of Luxrender, that represents a
    PointLight object
    """
    # This is where you write the renderer-specific code
    # to export the point light in the renderer format

    # From Luxcore doc:
    # power is in watts
    # efficency (sic) is in lumens/watt
    efficency = 15  # incandescent light bulb ratio (average)
    gain = 10  # Guesstimated! (don't hesitate to propose more sensible values)

    snippet = """
    # Generated by FreeCAD (http://www.freecadweb.org)
    AttributeBegin # {n}
    Transform [1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1]
    LightSource "point"
         "float from"        [{f.x} {f.y} {f.z}]
         "color L"           [{L[0]} {L[1]} {L[2]}]
         "float power"       [{p}]
         "float efficency"   [{e}]
         "float gain"        [{g}]
    AttributeEnd # {n}
    \n"""

    return dedent(snippet).format(n=view.Name,
                                  f=location,
                                  L=color,
                                  p=power,
                                  e=efficency,
                                  g=gain)


def write_arealight(name, pos, size_u, size_v, color, power):
    """Compute a string in the format of Luxrender, that represents an
    Area Light object
    """
    efficency = 150
    gain = 100  # Guesstimated! (don't hesitate to propose more sensible values)

    # We have to transpose 'pos' to make it fit for Lux
    # As 'transpose' method is in-place, we first make a copy
    placement = App.Matrix(pos.toMatrix())
    placement.transpose()
    trans = ' '.join([str(a) for a in placement.A])

    snippet = """
    # Generated by FreeCAD (http://www.freecadweb.org)
    AttributeBegin # {n}
    Transform [{t}]
    # NamedMaterial "{n}_mat"
    AreaLightSource "area"
        "color L"           [{L[0]} {L[1]} {L[2]}]
        "float power"       [{p}]
        "float efficency"   [{e}]
        "float importance"  [1.000000000000000]
        "float gain"        [{g}]
    Shape "mesh"
        "point P" [-{u} -{v} 0.0 {u} -{v} 0.0 {u} {v} 0.0 -{u} {v} 0.0]
        "integer triindices" [0 1 2 0 2 3]
        "bool generatetangents" ["false"]
        "string name" ["{n}"]
    AttributeEnd # {n}
    \n"""
    # TODO there is a scale problem (seems to be half too small)
    return dedent(snippet).format(n=name,
                                  t=trans,
                                  L=color,
                                  p=power,
                                  e=efficency,
                                  g=gain,
                                  u=size_u / 2,
                                  v=size_v / 2,
                                  )


def render(project, prefix, external, output, width, height):
    """Run Luxrender

    Params:
    - project:  the project to render
    - prefix:   a prefix string for call (will be inserted before path to Lux)
    - external: a boolean indicating whether to call UI (true) or console
                (false) version of Lux
    - width:    rendered image width, in pixels
    - height:   rendered image height, in pixels

    Return: void
    """
    # Here you trigger a render by firing the renderer
    # executable and passing it the needed arguments, and
    # the file it needs to render

    # change image size in template
    with open(project.PageResult, "r") as f:
        template = f.read()

    res = re.findall("integer xresolution", template)
    if res:
        template = re.sub(r'"integer xresolution".*?\[.*?\]',
                          '"integer xresolution" [{}]'.format(width),
                          template)

    res = re.findall("integer yresolution", template)
    if res:
        template = re.sub(r'"integer yresolution".*?\[.*?\]',
                          '"integer yresolution" [{}]'.format(height),
                          template)

    if res:
        f_handle, f_path = mkstemp(
            prefix=project.Name,
            suffix=os.path.splitext(project.Template)[-1])
        os.close(f_handle)
        with open(f_path, "w") as f:
            f.write(template)
        project.PageResult = f_path
        os.remove(f_path)
        App.ActiveDocument.recompute()

    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")
    args = params.GetString("LuxParameters", "")
    rpath = params.GetString("LuxRenderPath" if external
                             else "LuxConsolePath", "")
    if not rpath:
        App.Console.PrintError("Unable to locate renderer executable. "
                               "Please set the correct path in "
                               "Edit -> Preferences -> Render")
        return

    # Call Luxrender
    cmd = prefix + rpath + " " + args + " " + project.PageResult + "\n"
    App.Console.PrintMessage(cmd)
    try:
        Popen(shlex.split(cmd))
    except OSError as err:
        msg = "Luxrender call failed: '" + err.strerror + "'\n"
        App.Console.PrintError(msg)

    return
