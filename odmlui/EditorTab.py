from gi import pygtkcompat

pygtkcompat.enable()
pygtkcompat.enable_gtk(version='3.0')

import gtk
import os.path

import odml
import odml.validation
from odml.tools.odmlparser import ODMLReader, ODMLWriter, allowed_parsers

from .CommandManager import CommandManager
from .Helpers import uri_to_path, get_parser_for_uri, get_extension, create_pseudo_values
from .MessageDialog import ErrorDialog
from .treemodel import event
from .ValidationWindow import ValidationWindow


class EditorTab(object):
    """
    Represents a Document Object in the Editor
    """
    file_uri = None
    edited = 0

    def __init__(self, window, cmdm=None):
        if cmdm is None:
            cmdm = CommandManager()
            cmdm.enable_undo = self.enable_undo
            cmdm.enable_redo = self.enable_redo
            cmdm.error_func = window.command_error
        self.command_manager = cmdm
        self.document = None
        self.window = window
        self._clones = [self]

    def new(self, doc=None):
        """
        initialize a new document
        """
        if doc is None:
            doc = odml.Document()
            sec = odml.Section(name="Default Section")
            doc.append(sec)

        self.window.registry.add(doc)

        self.document = doc
        self.file_uri = None

    def parse_properties(self, odml_sections):
        for i in odml_sections:
            create_pseudo_values(i.properties)
            self.parse_properties(i.sections)

    def load(self, uri):
        self.file_uri = uri
        file_path = uri_to_path(uri)
        parser = get_parser_for_uri(file_path)
        odml_reader = ODMLReader(parser=parser)
        try:
            self.document = odml_reader.from_file(file_path)
        except Exception as e:
            ErrorDialog(None, "Error while parsing '%s'" % file_path, str(e))
            return False

        self.document.finalize()
        self.parse_properties(self.document.sections)
        self.window.registry.add(self.document)
        self.window._info_bar.show_info("Loading of %s done!" % (os.path.basename(file_path)))
        # TODO select default section
        return True

    def reset(self):
        self.edited = 0  # initialize the edit stack position
        self.command_manager.reset()
        self.enable_undo(enable=False)
        self.enable_redo(enable=False)

    @property
    def is_modified(self):
        return self.edited != len(self.command_manager)

    def save_if_changed(self):
        """
        if the document was modified, ask the user if he or she wants to save the document

        returns false if the user cancelled the action
        """
        if not self.is_modified:
            return True

        dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL,
                                   gtk.MESSAGE_INFO, gtk.BUTTONS_YES_NO,
                                   "%s has been modified. Do you want to save your changes?" % self.file_uri)

        dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)
        dialog.set_title("Save changes?")
        dialog.set_default_response(gtk.RESPONSE_CANCEL)

        response = dialog.run()
        dialog.destroy()

        if response == gtk.RESPONSE_CANCEL:
            return False
        if response == gtk.RESPONSE_NO:
            return True
        return self.window.save(None)

    def save(self, uri):
        # Mandatory document validation before save to avoid
        # not being able to open an invalid document.
        self.remove_validation()
        validation = odml.validation.Validation(self.document)
        self.document.validation_result = validation

        for e in self.document.validation_result.errors:
            if e.is_error:
                self.window._info_bar.show_info("Invalid document. Please fix errors (red) before saving.")
                self.validate()
                return

        self.document.clean()
        parser = get_parser_for_uri(uri)
        odml_writer = ODMLWriter(parser=parser)
        file_path = uri_to_path(uri)
        ext = get_extension(file_path)
        if ext.upper() not in allowed_parsers:
            file_path += '.xml'

        try:
            odml_writer.write_file(self.document, file_path)
        except Exception as e:
            self.window._info_bar.show_info("Save failed: %s" % e)
            return

        self.document.finalize()  # undo the clean
        self.window._info_bar.show_info("%s was saved" % (os.path.basename(file_path)))
        self.edited = len(self.command_manager)
        return True  # TODO return false on any error and notify the user

    def enable_undo(self, enable=True):
        for tab in self._clones:
            tab._enable_undo(enable)

    def _enable_undo(self, enable):
        if self.window.current_tab is self:
            self.window.enable_undo(enable)

    def enable_redo(self, enable=True):
        for tab in self._clones:
            tab._enable_redo(enable)

    def _enable_redo(self, enable=True):
        if self.window.current_tab is self:
            self.window.enable_redo(enable)

    def clone(self, klass=None):
        if klass is None:
            klass = self.__class__
        ntab = klass(self.window, self.command_manager)
        self._clones.append(ntab)
        ntab._clones = self._clones
        ntab.file_uri = self.file_uri
        ntab.document = self.document
        return ntab

    def clone_mapping(self):
        """
        create a mapped clone of this tab

        if there is a mapped clone already for this document
        find it and return its clone

        otherwise clone this tab and replace its document
        with the mapping
        """
        for tab in self._clones:
            if isinstance(tab, MappingEditorTab):
                return tab.clone()

        mapdoc = odml.mapping.create_mapping(tab.document)
        self.window.registry.add(mapdoc)
        ntab = self.clone(MappingEditorTab)
        ntab.document = mapdoc
        return ntab

    def validate(self):
        """check the document for errors"""
        self.remove_validation()
        validation = odml.validation.Validation(self.document)
        self.document.validation_result = validation
        if len(validation.errors) > 0:
            self.update_validation_error_objects(validation.errors)
            ValidationWindow(self).show()
        else:
            self.window._info_bar.show_info("The document is valid. No errors found.")
            self.remove_validation()

    def update_validation_error_objects(self, errors):
        """
        send out a change event for all error-affected objects
        so that the gui can refresh these
        """
        for err in errors:
            c = event.ChangeContext(('_error', True))
            c.post_change = True
            c.action = "set"
            c.pass_on(err.obj)

    def remove_validation(self):
        """remove any dangling validation references"""
        if not hasattr(self.document, "validation_result"):
            return
        errors = self.document.validation_result.errors
        del self.document.validation_result
        self.update_validation_error_objects(errors)

    def get_name(self):
        """return the filename of this tab's document"""
        return os.path.basename(str(self.file_uri))

    def update_label(self):
        """update the tab label with the current filename"""
        self.label.set_text(self.get_name())

    def close(self):
        """
        any cleanup?
        """
        self._clones.remove(self)


class MappingEditorTab(EditorTab):
    def close(self):
        super(MappingEditorTab, self).close()
        if not [x for x in self._clones if isinstance(x, MappingEditorTab)]:
            # no more mappings present, go unmap
            odml.mapping.unmap_document(self.document._proxy_obj)

    def get_name(self):
        return "map: %s" % super(MappingEditorTab, self).get_name()
