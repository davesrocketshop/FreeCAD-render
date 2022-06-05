# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2020 Howetuft <howetuft@gmail.com>                      *
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

"""LuxCore renderer plugin for FreeCAD Render workbench."""

# Suggested links to renderer documentation:
# https://wiki.luxcorerender.org/LuxCore_SDL_Reference_Manual_v2.6

import os
from tempfile import mkstemp
from textwrap import dedent, indent
import configparser

import FreeCAD as App

TEMPLATE_FILTER = "Luxcore templates (luxcore_*.cfg)"

# ===========================================================================
#                             Write functions
# ===========================================================================


def write_mesh(name, mesh, material):
    """Compute a string in renderer SDL to represent a FreeCAD mesh."""
    # Material
    snippet_mat = _write_material(name, material)

    # Core
    topology = mesh.Topology  # Compute once

    points = [f"{v.x} {v.y} {v.z}" for v in topology[0]]
    points = " ".join(points)
    tris = [f"{t[0]} {t[1]} {t[2]}" for t in topology[1]]
    tris = " ".join(tris)

    snippet_obj = f"""
    # Object '{name}'
    scene.objects.{name}.type = inlinedmesh
    scene.objects.{name}.vertices = {points}
    scene.objects.{name}.faces = {tris}
    scene.objects.{name}.material = {name}
    scene.objects.{name}.transformation = 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1
    """

    # UV map
    if mesh.has_uvmap():
        uvs = [f"{t.x} {t.y}" for t in mesh.uvmap]
        uvs = " ".join(uvs)
        snippet_uv = f"""scene.objects.{name}.uvs = {uvs}\n"""
    else:
        snippet_uv = ""

    # Consolidation
    snippet = snippet_obj + snippet_uv + snippet_mat
    return dedent(snippet)


def write_camera(name, pos, updir, target, fov):
    """Compute a string in renderer SDL to represent a camera."""
    snippet = """
    # Camera '{n}'
    scene.camera.lookat.orig = {o.x} {o.y} {o.z}
    scene.camera.lookat.target = {t.x} {t.y} {t.z}
    scene.camera.up = {u.x} {u.y} {u.z}
    scene.camera.fieldofview = {f}
    """
    return dedent(snippet).format(n=name, o=pos.Base, t=target, u=updir, f=fov)


def write_pointlight(name, pos, color, power):
    """Compute a string in renderer SDL to represent a point light."""
    # From LuxCore doc:
    # power is in watts
    # efficiency is in lumens/watt
    efficiency = 15  # incandescent light bulb ratio (average)
    gain = 10  # Guesstimated! (don't hesitate to propose more sensible values)

    snippet = """
    # Point light '{n}'
    scene.lights.{n}.type = point
    scene.lights.{n}.position = {o.x} {o.y} {o.z}
    scene.lights.{n}.color = {c[0]} {c[1]} {c[2]}
    scene.lights.{n}.power = {p}
    scene.lights.{n}.gain = {g} {g} {g}
    scene.lights.{n}.efficency = {e}
    """
    return dedent(snippet).format(
        n=name, o=pos, c=color, p=power, g=gain, e=efficiency
    )


def write_arealight(name, pos, size_u, size_v, color, power, transparent):
    """Compute a string in renderer SDL to represent an area light."""
    efficiency = 15
    gain = 0.001  # Guesstimated!

    # We have to transpose 'pos' to make it fit for Lux
    # As 'transpose' method is in-place, we first make a copy
    placement = App.Matrix(pos.toMatrix())
    placement.transpose()
    trans = " ".join([str(a) for a in placement.A])

    snippet = """
    # Area light '{n}'
    scene.materials.{n}.type = matte
    scene.materials.{n}.emission = {c[0]} {c[1]} {c[2]}
    scene.materials.{n}.emission.gain = {g} {g} {g}
    scene.materials.{n}.emission.power = {p}
    scene.materials.{n}.emission.efficency = {e}
    scene.materials.{n}.transparency = {a}
    scene.materials.{n}.kd = 0.0 0.0 0.0
    scene.objects.{n}.type = inlinedmesh
    scene.objects.{n}.vertices = -{u} -{v} 0 {u} -{v} 0 {u} {v} 0 -{u} {v} 0
    scene.objects.{n}.faces = 0 1 2 0 2 3 0 2 1 0 3 2
    scene.objects.{n}.material = {n}
    scene.objects.{n}.transformation = {t}
    """
    # Note: area light is made double-sided (consistency with other renderers)

    return dedent(snippet).format(
        n=name,
        t=trans,
        c=color,
        p=power,
        e=efficiency,
        g=gain,
        u=size_u / 2,
        v=size_v / 2,
        a=0 if transparent else 1,
    )


def write_sunskylight(name, direction, distance, turbidity, albedo):
    """Compute a string in renderer SDL to represent a sunsky light."""
    snippet = """
    # Sunsky light '{n}'
    scene.lights.{n}_sun.type = sun
    scene.lights.{n}_sun.turbidity = {t}
    scene.lights.{n}_sun.dir = {d.x} {d.y} {d.z}
    scene.lights.{n}_sky.type = sky2
    scene.lights.{n}_sky.turbidity = {t}
    scene.lights.{n}_sky.dir = {d.x} {d.y} {d.z}
    scene.lights.{n}_sky.groundalbedo = {g} {g} {g}
    """
    return dedent(snippet).format(n=name, t=turbidity, d=direction, g=albedo)


def write_imagelight(name, image):
    """Compute a string in renderer SDL to represent an image-based light."""
    snippet = """
    # Image light '{n}'
    scene.lights.{n}.type = infinite
    scene.lights.{n}.transformation = -1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1
    scene.lights.{n}.file = "{f}"
    """
    return dedent(snippet).format(n=name, f=image)


# ===========================================================================
#                              Material implementation
# ===========================================================================

# TODO Fix normals issue (see Gauge test file, with mirror)


def _write_material(name, material):
    """Compute a string in the renderer SDL, to represent a material.

    This function should never fail: if the material is not recognized,
    a fallback material is provided.
    """
    try:
        snippet_mat = MATERIALS[material.shadertype](name, material)
    except KeyError:
        msg = (
            "'{}' - Material '{}' unknown by renderer, using fallback "
            "material\n"
        )
        App.Console.PrintWarning(msg.format(name, material.shadertype))
        snippet_mat = _write_material_fallback(name, material.default_color)
    return snippet_mat


def _write_material_passthrough(name, material):
    """Compute a string in the renderer SDL for a passthrough material."""
    assert material.passthrough.renderer == "Luxcore"
    snippet = indent(material.passthrough.string, "    ")
    return snippet.format(n=name, c=material.default_color)


def _write_material_glass(name, material):
    """Compute a string in the renderer SDL for a glass material."""
    textures_text = _write_textures(name, material.glass)
    snippet = """
    scene.materials.{n}.type = glass
    scene.materials.{n}.kt = {c}
    scene.materials.{n}.interiorior = {i}
    """
    material_text = snippet.format(
        n=name,
        c=_color(material.glass.color, name),
        i=_float(material.glass.ior, name),
    )
    return material_text + textures_text


def _write_material_disney(name, material):
    """Compute a string in the renderer SDL for a Disney material."""
    textures_text = _write_textures(name, material.disney)
    snippet = """
    scene.materials.{0}.type = disney
    scene.materials.{0}.basecolor = {1}
    scene.materials.{0}.subsurface = {2}
    scene.materials.{0}.metallic = {3}
    scene.materials.{0}.specular = {4}
    scene.materials.{0}.speculartint = {5}
    scene.materials.{0}.roughness = {6}
    scene.materials.{0}.anisotropic = {7}
    scene.materials.{0}.sheen = {8}
    scene.materials.{0}.sheentint = {9}
    scene.materials.{0}.clearcoat = {10}
    scene.materials.{0}.clearcoatgloss = {11}
    """
    material_text = snippet.format(
        name,
        _color(material.disney.basecolor, name),
        _float(material.disney.subsurface, name),
        _float(material.disney.metallic, name),
        _float(material.disney.specular, name),
        _float(material.disney.speculartint, name),
        _float(material.disney.roughness, name),
        _float(material.disney.anisotropic, name),
        _float(material.disney.sheen, name),
        _float(material.disney.sheentint, name),
        _float(material.disney.clearcoat, name),
        _float(material.disney.clearcoatgloss, name),
    )
    return material_text + textures_text


def _write_material_diffuse(name, material):
    """Compute a string in the renderer SDL for a Diffuse material."""
    textures_text = _write_textures(name, material.diffuse)
    snippet = """
    scene.materials.{n}.type = matte
    scene.materials.{n}.kd = {c}
    """
    material_text = snippet.format(
        n=name, c=_color(material.diffuse.color, name)
    )
    return material_text + textures_text


def _write_material_mixed(name, material):
    """Compute a string in the renderer SDL for a Mixed material."""
    textures_text = _write_textures(name, material.mixed)
    snippet_g = _write_material_glass(f"{name}_glass", material.mixed)
    snippet_d = _write_material_diffuse(f"{name}_diffuse", material.mixed)
    snippet_m = """
    scene.materials.{n}.type = mix
    scene.materials.{n}.material1 = {n}_diffuse
    scene.materials.{n}.material2 = {n}_glass
    scene.materials.{n}.amount = {r}
    """
    snippet = snippet_g + snippet_d + snippet_m
    material_text = snippet.format(
        n=name, r=_float(material.mixed.transparency, name)
    )

    return material_text + textures_text


def _write_material_carpaint(name, material):
    """Compute a string in the renderer SDL for a carpaint material."""
    textures_text = _write_textures(name, material.carpaint)
    snippet = """
    scene.materials.{n}.type = carpaint
    scene.materials.{n}.kd = {c}
    """
    material_text = snippet.format(
        n=name, c=_color(material.carpaint.basecolor, name)
    )
    return material_text + textures_text


def _write_material_fallback(name, material):
    """Compute a string in the renderer SDL for a fallback material.

    Fallback material is a simple Diffuse material.
    """
    try:
        red = float(material.default_color.r)
        grn = float(material.default_color.g)
        blu = float(material.default_color.b)
        assert (0 <= red <= 1) and (0 <= grn <= 1) and (0 <= blu <= 1)
    except (AttributeError, ValueError, TypeError, AssertionError):
        red, grn, blu = 1, 1, 1
    snippet = """
    scene.materials.{n}.type = matte
    scene.materials.{n}.kd = {r} {g} {b}
    """
    return snippet.format(n=name, r=red, g=grn, b=blu)


MATERIALS = {
    "Passthrough": _write_material_passthrough,
    "Glass": _write_material_glass,
    "Disney": _write_material_disney,
    "Diffuse": _write_material_diffuse,
    "Mixed": _write_material_mixed,
    "Carpaint": _write_material_carpaint,
}

# ===========================================================================
#                           Texture management
# ===========================================================================


def _write_textures(name, submaterial):
    """Compute textures string for a given submaterial."""
    # TODO Fix uvscale (inverse scaling?)
    snippet = """
    scene.textures.{n}.type = imagemap
    scene.textures.{n}.file = "{f}"
    scene.textures.{n}.gamma = 2.2
    scene.textures.{n}.mapping.type = uvmapping2d
    scene.textures.{n}.mapping.rotation = {r}
    scene.textures.{n}.mapping.uvscale = {su} {sv}
    scene.textures.{n}.mapping.uvdelta = {tu} {tv}
    """
    textures = []
    for value in submaterial.__dict__.values():
        try:
            texname = f"{name}_{value.name}_{value.subname}"
            texture = snippet.format(
                n=texname,
                f=value.file,
                r=float(value.rotation),
                su=float(value.scale_u),
                sv=float(value.scale_v),
                tu=float(value.translation_u),
                tv=float(value.translation_v),
            )
        except AttributeError:
            pass
        else:
            textures.append(texture)
    return "\n".join(textures)


def _color(value, material_name):
    """Write a color in a material, with texture support."""
    # Plain color
    try:
        res = f"{value.r} {value.g} {value.b}"
    except AttributeError:
        pass
    else:
        return res
    # Texture
    try:
        res = f"{material_name}_{value.name}_{value.subname}"
    except AttributeError:
        pass
    else:
        return res
    # No match - raise exception
    raise ValueError


def _float(value, material_name):
    """Write a float in a material, with texture support."""
    # Plain float
    try:
        res = f"{float(value)}"
    except (ValueError, TypeError):
        pass
    else:
        return res
    # Texture
    try:
        res = f"{material_name}_{value.name}_{value.subname}"
    except AttributeError:
        pass
    else:
        return res
    # No match - raise exception
    raise ValueError


# ===========================================================================
#                              Render function
# ===========================================================================


def render(project, prefix, external, output, width, height):
    """Generate renderer command.

    Args:
        project -- The project to render
        prefix -- A prefix string for call (will be inserted before path to
            renderer)
        external -- A boolean indicating whether to call UI (true) or console
            (false) version of renderder
        width -- Rendered image width, in pixels
        height -- Rendered image height, in pixels

    Returns:
        The command to run renderer (string)
        A path to output image file (string)
    """

    def export_section(section, prefix, suffix):
        """Export a section to a temporary file."""
        f_handle, f_path = mkstemp(prefix=prefix, suffix="." + suffix)
        os.close(f_handle)
        result = [f"{k} = {v}" for k, v in dict(section).items()]
        with open(f_path, "w", encoding="utf-8") as output:
            output.write("\n".join(result))
        return f_path

    # LuxCore requires 2 files:
    # - a configuration file, with rendering parameters (engine, sampler...)
    # - a scene file, with the scene objects (camera, lights, meshes...)
    # So we have to generate both...

    # Get page result content (ie what the calling module baked for us)
    pageresult = configparser.ConfigParser(strict=False)  # Allow dupl. keys
    pageresult.optionxform = lambda option: option  # Case sensitive keys
    pageresult.read(project.PageResult)

    # Compute output
    output = (
        output if output else os.path.splitext(project.PageResult)[0] + ".png"
    )

    # Export configuration
    config = pageresult["Configuration"]
    config["film.width"] = str(width)
    config["film.height"] = str(height)
    config["film.outputs.0.type"] = "RGB_IMAGEPIPELINE"
    config["film.outputs.0.filename"] = output
    config["film.outputs.0.index"] = "0"
    config["periodicsave.film.outputs.period"] = "1"
    cfg_path = export_section(config, project.Name, "cfg")

    # Export scene
    scene = pageresult["Scene"]
    scn_path = export_section(scene, project.Name, "scn")

    # Get rendering parameters
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")
    args = params.GetString("LuxCoreParameters", "")
    rpath = params.GetString(
        "LuxCorePath" if external else "LuxCoreConsolePath", ""
    )
    if not rpath:
        msg = (
            "Unable to locate renderer executable. Please set the correct "
            "path in Edit -> Preferences -> Render\n"
        )
        App.Console.PrintError(msg)
        return None, None

    # Prepare command line and return
    cmd = f"""{prefix}{rpath} {args} -o "{cfg_path}" -f "{scn_path}"\n"""

    return cmd, output
