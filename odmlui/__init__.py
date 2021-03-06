from odmlui.info import VERSION as __version__
from odmlui.info import HOMEPAGE

try:
    import gi
    import pygtkcompat
    pygtkcompat.enable()
    pygtkcompat.enable_gtk(version='3.0')
    import gtk
    import gobject
except (ImportError, ValueError) as err:
    DEP_STR = "Non-Python dependency missing, check the " \
              "install instructions at %s." % HOMEPAGE
    print("\n %s\n\n%s" % (err, DEP_STR))
    exit(1)

DEBUG = False
