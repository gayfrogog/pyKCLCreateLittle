import os
import btypes
import kcl

from PyQt5 import QtCore,QtGui,QtWidgets

#------------------------------------------------------------------------------

class OctreeWidget(QtWidgets.QGroupBox):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)

        self.max_triangles = QtWidgets.QSpinBox(self)
        self.max_triangles.setRange(1,99) #FIXME: find better upper bound?
        self.max_triangles.setValue(25)

        self.min_width = QtWidgets.QSpinBox(self)
        self.min_width.setRange(1,2048) #FIXME: find better upper bound?
        self.min_width.setValue(8)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel('Max. triangles per cube:',self),0,0)
        grid.addWidget(self.max_triangles,0,1)
        grid.addWidget(QtWidgets.QLabel('Min. cube width:',self),1,0)
        grid.addWidget(self.min_width,1,1)
        self.setLayout(grid)

    def maxTriangles(self):
        return self.max_triangles.value()

    def minWidth(self):
        return self.min_width.value()

#------------------------------------------------------------------------------

class GroupWidget(QtWidgets.QGroupBox):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)

        self.current_type = None

        self.group_list = QtWidgets.QListWidget()
        self.group_list.setMinimumWidth(20*QtGui.QFontMetrics(self.group_list.font()).averageCharWidth())
        self.group_list.currentRowChanged.connect(self.onCurrentGroupChanged)

        self.camera_id = QtWidgets.QSpinBox(self)
        self.camera_id.setRange(0,0xFF)

        self.sound_code = QtWidgets.QComboBox(self)
        self.sound_code.addItems(kcl.SOUND_CODES)

        self.floor_code = QtWidgets.QComboBox(self)
        self.floor_code.addItems(kcl.FLOOR_CODES)

        self.wall_code = QtWidgets.QComboBox(self)
        self.wall_code.addItems(kcl.WALL_CODES)

        self.camera_through = QtWidgets.QCheckBox('Camera through',self)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(self.group_list,0,0,6,1)
        grid.addWidget(QtWidgets.QLabel('Camera ID:',self),0,1)
        grid.addWidget(self.camera_id,0,2)
        grid.addWidget(QtWidgets.QLabel('Sound code:',self),1,1)
        grid.addWidget(self.sound_code,1,2)
        grid.addWidget(QtWidgets.QLabel('Floor code:',self),2,1)
        grid.addWidget(self.floor_code,2,2)
        grid.addWidget(QtWidgets.QLabel('Wall code:',self),3,1)
        grid.addWidget(self.wall_code,3,2)
        grid.addWidget(self.camera_through,4,1,1,2)
        self.setLayout(grid)

    def setGroups(self,group_names,surface_types):
        self.group_list.clear()
        self.group_list.addItems(group_names)
        self.surface_types = surface_types
        self.current_type = None

    def onCurrentGroupChanged(self,group):
        if self.current_type is not None:
            self.current_type.camera_id = self.camera_id.value()
            self.current_type.sound_code = self.sound_code.currentIndex()
            self.current_type.floor_code = self.floor_code.currentIndex()
            self.current_type.wall_code = self.wall_code.currentIndex()
            self.current_type.camera_through = self.camera_through.isChecked()

        self.current_type = self.surface_types[group]
        self.camera_id.setValue(self.current_type.camera_id)
        self.sound_code.setCurrentIndex(self.current_type.sound_code)
        self.floor_code.setCurrentIndex(self.current_type.floor_code)
        self.wall_code.setCurrentIndex(self.current_type.wall_code)
        self.camera_through.setChecked(self.current_type.camera_through)

#------------------------------------------------------------------------------

class BuilderThread(QtCore.QThread):

    def __init__(self,parent,filename,triangles,max_triangles,min_width,surface_types):
        super().__init__(parent)
        self.filename = filename
        self.triangles = triangles
        self.max_triangles = max_triangles
        self.min_width = min_width
        self.surface_types = surface_types

    geometryOverflow = QtCore.pyqtSignal(kcl.GeometryOverflowError)

    def run(self):
        try:
            with btypes.FileStream(self.filename[0],'wb',btypes.LITTLE_ENDIAN) as stream:
                kcl.pack(stream,self.triangles,self.max_triangles,self.min_width)
            with btypes.FileStream(os.path.splitext(self.filename[0])[0] + '.pa','wb',btypes.LITTLE_ENDIAN) as stream:
                kcl.SurfaceTypeList.pack(stream,self.surface_types)
        except kcl.GeometryOverflowError as error:
            self.geometryOverflow.emit(error)


class UnclosableProgressDialog(QtWidgets.QProgressDialog):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.is_closable = False

    def closeEvent(self,event):
        if not self.is_closable:
            event.ignore()
        else:
            super().closeEvent(event)

    def close(self):
        self.is_closable = True
        super().close()


class CollisionWidget(QtWidgets.QWidget):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)

        self.octree = OctreeWidget('Octree',self)
        self.groups = GroupWidget('Groups',self)

        vbox = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.octree,0)
        vbox.addWidget(self.groups,1)
        self.setLayout(vbox)

    def load(self,filename):
        with open(os.path.normpath(filename)) as stream:
            self.triangles = kcl.WavefrontOBJ.unpack(stream)
        self.groups.setGroups(self.triangles.group_names,[kcl.SurfaceType() for _ in self.triangles.group_names])

    def save(self,filename):
        progress_dialog = UnclosableProgressDialog(self)
        progress_dialog.setWindowTitle('Save Collision')
        progress_dialog.setLabelText('Building collision...')
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimum(0)
        progress_dialog.setMaximum(0)
        progress_dialog.setModal(True)
        progress_dialog.show()

        builder_thread = BuilderThread(self,filename,self.triangles,self.octree.maxTriangles(),self.octree.minWidth(),self.groups.surface_types)
        builder_thread.finished.connect(progress_dialog.close)
        builder_thread.geometryOverflow.connect(self.onGeometryOverflow)
        builder_thread.start()

    def onGeometryOverflow(self,error):
        message = QtGui.QMessageBox(self)
        message.setIcon(QtGui.QMessageBox.Critical)
        message.setText('GeometryOverflowError: {}.'.format(error))
        message.setInformativeText('Try reducing the number of triangles in the model.')
        message.setStandardButtons(QtGui.QMessageBox.Ok)
        message.setDefaultButton(QtGui.QMessageBox.Ok)
        message.exec_()

#------------------------------------------------------------------------------

class CollisionEditor(QtWidgets.QMainWindow):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        
        self.open_action = QtWidgets.QAction('&Open',self)
        self.open_action.setShortcut('Ctrl+O')
        self.open_action.triggered.connect(self.onOpen)

        self.save_action = QtWidgets.QAction('&Save',self)
        self.save_action.setShortcut('Ctrl+S')
        self.save_action.triggered.connect(self.onSave)
        self.save_action.setEnabled(False)

        self.saveas_action = QtWidgets.QAction('Save &As',self)
        self.saveas_action.setShortcut('Shift+Ctrl+S')
        self.saveas_action.triggered.connect(self.onSaveAs)
        self.saveas_action.setEnabled(False)

        self.exit_action = QtWidgets.QAction('&Exit',self)
        self.exit_action.setShortcut('Ctrl+Q')
        self.exit_action.triggered.connect(QtWidgets.QApplication.quit)

        menubar = self.menuBar()
        file_menu = menubar.addMenu('&File')
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.saveas_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        self.collision_widget = CollisionWidget(self)
        self.setCentralWidget(self.collision_widget)

        # This is just to set the window title
        self.setWindowFilePath('[No File]')

        self.resize(0,0)

    def load(self,filename):
        self.collision_widget.load(os.path.normpath(filename))
        self.setWindowFilePath(os.path.splitext(filename)[0] + '.kcl')
        self.save_action.setEnabled(True)
        self.saveas_action.setEnabled(True)

    def onOpen(self):
        filename = QtWidgets.QFileDialog.getOpenFileName(self,'Open File',self.windowFilePath(),'Wavefront OBJ (*.obj);;All files (*)')
        if not filename: return
        self.load(os.path.normpath(filename[0]))

    def onSave(self):
        self.collision_widget.save(self.windowFilePath())

    def onSaveAs(self):
        filename = QtWidgets.QFileDialog.getSaveFileName(self,'Save File',self.windowFilePath(),'SMG KCL (*.kcl);;All files (*)')
        if not filename: return
        self.collision_widget.save(filename)
        self.setWindowFilePath(os.path.normpath(filename[0]))

#------------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    application = QtWidgets.QApplication(sys.argv)
    application.setApplicationName('Collision Creator')
    editor = CollisionEditor()
    if len(sys.argv) > 1:
        editor.load(sys.argv[1])
    editor.show()
    sys.exit(application.exec_())

#______________________________________________________________________________
