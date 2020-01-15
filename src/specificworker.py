#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 by YOUR NAME HERE
#
#    This file is part of RoboComp
#
#    RoboComp is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    RoboComp is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with RoboComp.  If not, see <http://www.gnu.org/licenses/>.
#

from genericworker import *

# If RoboComp was compiled with Python bindings you can use InnerModel in Python
# sys.path.append('/opt/robocomp/lib')
# import librobocomp_qmat
# import librobocomp_osgviewer
# import librobocomp_innermodel
import os
from FileManager import save_info, FileManager, get_saved_info, url, get_weight
from PySide2 import QtCore
from rs_camera import RSCamera, config_devices
from lamb_filter import isThereALamb
import signal
from telebot_messages import send_msg, start_bot
from keras import models
from threading import Thread


class SpecificWorker(GenericWorker):
    def __init__(self, proxy_map):
        super(SpecificWorker, self).__init__(proxy_map)
        self.exit = False
        self.no_cam = 0
        self.no_memory = 0
        self.Period = 1000  # 1 second for frame

        self.timer.setInterval(self.Period)
        self.timer.setSingleShot(True)

        self.Info_period = 1000 * 60 * 60 * 8  # 8h for get an info message
        self.info_timer = QtCore.QTimer(self)
        self.info_timer.setInterval(self.Info_period)
        self.info_timer.setSingleShot(True)

        self.cameras = None
        self.top_camera = None
        self.back_camera = None
        self.lamb_label = ""
        self.frame = (None, None)
        self.weight = 0.0

        self.telegram_bot = Thread(target=start_bot)
        self.telegram_bot.start()

        self.Application.start()

        # Load the CNN model with the path to the .h5 model path
        self.CNNmodel = models.load_model(os.path.join(os.path.expanduser('~'), 'LambNN', "etc", "CNN_model.h5"))

    def receive_signal(self, signum, stack):
        print("\n\n\t[eCtrl + C]\n\n")
        self.exit = True

    def __del__(self):
        print('SpecificWorker destructor')

    def setParams(self, params):
        # try:
        #	self.innermodel = InnerModel(params["InnerModelPath"])
        # except:
        #	traceback.print_exc()
        #	print("Error reading config params")
        return True

    # =============== Slots methods for State Machine ===================
    # ===================================================================
    #
    # sm_init
    #
    @QtCore.Slot()
    def sm_init(self):
        """ First state of the state machine, it triggers the LambScan main state """
        print("Entered state init")
        send_msg("LambNN started")
        signal.signal(signal.SIGINT, self.receive_signal)
        self.t_init_to_lambscan.emit()

    #
    # sm_lambscan
    #
    @QtCore.Slot()
    def sm_lambscan(self):
        """ The main state of the state machine, it is a sub state machine itself."""
        print("Entered state lambscan")

    #
    # sm_end
    #
    @QtCore.Slot()
    def sm_end(self):
        """ Its closes the whole application and exit of the program.
        it's the last state of the state machine. """
        print("Entered state end")
        self.Application.stop()
        from PySide2.QtWidgets import QApplication
        QApplication.quit()

    #
    # sm_start_streams
    #
    @QtCore.Slot()
    def sm_start_streams(self):
        print("Entered state start_streams")
        started = True
        try:
            self.camera = config_devices()
            for cam in self.cameras:
                started = True if cam.start() and started else False
            if started:
                self.info_timer.start()
                self.t_start_streams_to_get_frames.emit()
            else:
                raise Exception("It couldn't start the streams")
        except Exception as e:
            print("problem starting the streams of the camera\n", e)
            self.t_start_streams_to_no_camera.emit()

    #
    # sm_get_frames
    #
    @QtCore.Slot()
    def sm_get_frames(self):
        print("Entered state get_frames")
        if self.exit:
            print("\n\n\t[!] Ctrl + C received. Closing program...\n\n")
            self.t_get_frames_to_exit.emit()
        self.timer.start()
        if self.info_timer.remainingTime() == 0:
            send_msg(get_saved_info())
            self.info_timer.start()
        try:
            self.frame = self.cameras.get_frame()
            while self.timer.remainingTime() > 0:
                self.frame = self.cameras.get_frame()
            self.weight = get_weight()
            if self.weight is None:
                send_msg("Problem getting the json file from the weighing machine's url: {}".format(url))
            self.t_get_frames_to_processing_and_filter.emit()
        except Exception as e:
            print("An error occur when taking a new frame,:\n " + str(e))
            print(type(e))
            self.t_get_frames_to_no_camera.emit()

    #
    # sm_no_camera
    #
    @QtCore.Slot()
    def sm_no_camera(self):
        print("Entered state no_camera")
        self.cameras.__del__()
        self.cameras = None
        self.no_cam += 1
        if self.no_cam >= 12:
            self.t_no_camera_to_send_message.emit()
        else:
            self.t_no_camera_to_start_streams.emit()

    #
    # sm_no_memory
    #
    @QtCore.Slot()
    def sm_no_memory(self):
        print("Entered state no_memory")
        self.no_memory += 1
        if self.no_memory > 2:
            self.t_no_memory_to_send_message.emit()
        else:
            self.t_no_memory_to_save.emit()

    #
    # sm_processing_and_filter
    #
    @QtCore.Slot()
    def sm_processing_and_filter(self):
        print("Entered state processing_and_filter")
        self.no_cam = 0
        must_save, self.lamb_label = isThereALamb(*self.frame, model=self.CNNmodel)
        if must_save:
            self.t_processing_and_filter_to_save.emit()
        else:
            self.t_processing_and_filter_to_get_frames.emit()

    #
    # sm_save
    #
    @QtCore.Slot()
    def sm_save(self):
        print("Entered state save")
        try:
            save_info(*self.frame, weight=self.weight, lamb_label=self.lamb_label)
            self.lamb_label = ""
            self.weight = 0.0
            self.t_save_to_get_frames.emit()
        except FileManager as e:
            print(("Problem saving the file\n", e))
            self.t_save_to_no_memory.emit()

    #
    # sm_send_message
    #
    @QtCore.Slot()
    def sm_send_message(self):
        if self.no_cam > 0:
            send_msg("[ ! ] Camara desconectada. " + str(self.no_cam) + " intentos de reconexion agotados.")
        elif self.no_memory > 0:
            send_msg("[ ! ] Error en la memoria del dispositivo. " + str(
                self.no_memory) + " intentos de escritura agotados.")
        else:
            send_msg("[ ? ] Estado SEND_MESSAGE incoherente. Se ha accedido a este estado sin que haya un error.")
        self.t_send_message_to_exit.emit()

    #
    # sm_exit
    #
    @QtCore.Slot()
    def sm_exit(self):
        print("Entered state exit")
        self.telegram_bot.do_run = False
        self.telegram_bot.join()
        # self.cameras.__del__()
        self.t_lambscan_to_end.emit()

# =================================================================
# =================================================================
