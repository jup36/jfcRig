# -*- coding: utf-8 -*-
# Jason Keller
# May 2019
# =============================================================================
#  Program to set BlackFly S camera settings and acquire frames and write them
#  to a compressed video file. Based on FLIR Spinnaker API example code
# 
#  The intent is that DAQ is started first, then this program will start
#  the camera with a software trigger and output ExposureActive signal on Line 1
#  (DAQ should sample this at 5kHz+) so that each frame can be synchronized. NOTE 
#  that from the penultimate image grab until EndAcquisition to stop Line 1 will 
#  take a few milliseconds, so the last AcquisitionActive edges can be discarded 
#  by the DAQ system
#
#  Tkinter is used to provide a simple GUI to dispaly the images, and skvideo 
#  is used as a wrapper to ffmpeg to write H.264 compressed video quickly
#

#
# TO DO:
# (1) report # missed / delayed frames somehow (maybe use counter to count Line 1 edges and write to video file)
# (2) 
# =============================================================================

import PySpin, time, threading, queue, os
from datetime import datetime
import tkinter as tk
from PIL import Image, ImageTk
import numpy as np
import skvideo
skvideo.setFFmpegPath('C:/Anaconda3/Lib/site-packages/ffmpeg') #set path to ffmpeg installation before importing io
import skvideo.io

#constants
SAVE_FOLDER_ROOT = 'C:/video'
FILENAME_ROOT = 'mj_' # for mouse jump files
#TIFNAME = 'test.tif' #btf for bigTif
EXPOSURE_TIME = 2150 # in microseconds; this determines frame rate
GAIN_VALUE = 25 #in dB, 0-40
SEC_TO_RECORD = 240 #approximate # seconds to record for; can also use Ctrl-C to interupt in middle of capture

# generate output video directory and filename and make sure not overwriting
now = datetime.now()
dateStr = now.strftime("%Y_%m_%d") #save folder ex: 2020_01_01
timeStr = now.strftime("%H_%M_%S") #filename ex: mj_09_30_59.mp4
saveFolder = SAVE_FOLDER_ROOT + '/' + dateStr
if not os.path.exists(saveFolder):
    os.mkdir(saveFolder)
os.chdir(saveFolder)
movieName = FILENAME_ROOT + timeStr + '.mp4'
fullFilePath = [saveFolder + '/' + movieName]
print('Video will be saved to: {}'.format(fullFilePath))

# Get camera system and set all parameters necessary:
system = PySpin.System.GetInstance() 
#system = PySpin.System.GetInstance() #JAK - make sure to actually get the instance
# Get camera list
cam_list = system.GetCameras()
cam = cam_list[0]
cam.Init()
# load default configuration
cam.UserSetSelector.SetValue(PySpin.UserSetSelector_Default)
cam.UserSetLoad()
# set acquisition. Continues acquisition. Auto exposure off. Set frame rate. 
cam.AcquisitionMode.SetValue(PySpin.AcquisitionMode_Continuous)
cam.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
cam.ExposureMode.SetValue(PySpin.ExposureMode_Timed)
cam.ExposureTime.SetValue(EXPOSURE_TIME)
cam.AcquisitionFrameRateEnable.SetValue(False)
# set analog. Set Gain. Turn off Gamma. 
cam.GainAuto.SetValue(PySpin.GainAuto_Off)
cam.Gain.SetValue(GAIN_VALUE)
cam.GammaEnable.SetValue(False)
# set ADC bit depth and image pixel depth 
cam.AdcBitDepth.SetValue(PySpin.AdcBitDepth_Bit10)
cam.PixelFormat.SetValue(PySpin.PixelFormat_Mono8)
# set digital I/O to output ExposureActive signal on Line1 (the white wire)
cam.LineSelector.SetValue(PySpin.LineSelector_Line1)
cam.LineMode.SetValue(PySpin.LineMode_Output) 
cam.LineSource.SetValue(PySpin.LineSource_ExposureActive) #route desired output to Line 1 (try Counter0Active or ExposureActive)
#cam.LineSelector.SetValue(PySpin.LineSelector_Line2)
#cam.V3_3Enable.SetValue(True) #enable 3.3V rail on Line 2 (red wire) to act as a pull up for ExposureActive 

# get frame rate and query for video length based on this
frameRate = cam.AcquisitionResultingFrameRate()
print('frame rate = {:.2f} FPS'.format(frameRate))
numImages = round(frameRate*SEC_TO_RECORD)
print('# frames = {:d}'.format(numImages))

def save_img(image_queue, writer, i):
    while True:
        dequeuedImage = image_queue.get() 
        if dequeuedImage is None:
            break
        else:
            writer.writeFrame(dequeuedImage)
            image_queue.task_done()

# setup output video file parameters (can try H265 in future for better compression):
# framerate does not seem to work without adding extra frames, so just accept default 25fps output and change elsewhere if needed            
crfOut = 25 #controls tradeoff between quality and storage, see https://trac.ffmpeg.org/wiki/Encode/H.264 
writer = skvideo.io.FFmpegWriter(movieName, outputdict={'-vcodec': 'libx264', '-crf' : str(crfOut)})

#setup tkinter GUI (non-blocking, i.e. without mainloop) to output images to screen quickly
window = tk.Tk()
window.title("camera acquisition")
window.geometry('740x570') #large enough for frame + text
textlbl = tk.Label(window, text="elapsed time: ")
textlbl.grid(column=0, row=0)
imglabel = tk.Label(window) # make Label widget to hold image
imglabel.place(x=10, y=20) #pixels from top-left
window.update() #update TCL tasks to make window appear

#############################################################################
# start main program loop ###################################################
#############################################################################    

try:
    print('Press Ctrl-C to exit early and save video')
    cam.BeginAcquisition()
    tStart = time.time()
    i = 0
    image_queue = queue.Queue() #create queue in memory to store images while asynchronously written to disk
    # setup another thread to accelerate saving, and start immediately:
    save_thread = threading.Thread(target=save_img, args=(image_queue, writer, i,))
    save_thread.start()  

    for i in range(numImages):
#    while True:
#        print(i)
        image = cam.GetNextImage() #get pointer to next image in camera buffer; blocks until image arrives via USB; timeout=INF 
        enqueuedImage = np.array(image.GetData(), dtype="uint8").reshape( (image.GetHeight(), image.GetWidth()) ); #convert PySpin ImagePtr into numpy array
        image_queue.put(enqueuedImage) #put next image in queue
        
        if i%10 == 0: #update screen every 10 frames 
            timeElapsed = str(time.time() - tStart)
            timeElapsedStr = "elapsed time: " + timeElapsed[0:5] + " sec"
            textlbl.configure(text=timeElapsedStr)
            I = ImageTk.PhotoImage(Image.fromarray(enqueuedImage))
            imglabel.configure(image=I)
            imglabel.image = I #keep reference to image
            window.update() #update on screen (this must be called from main thread)
            
        image.Release() #release from camera buffer
#        i += 1
#        frameNum = cam.EventExposureEndFrameID #perhaps count edges here
#        print(frameNum)
     
except KeyboardInterrupt: #if user hits Ctrl-C, everything should end gracefully
    pass        
        
# NOTE that from the penultimate image grab until EndAcquisition to stop Line 1 will take a few milliseconds,
# so the last AcquisitionActive edges can be discarded by the DAQ system
cam.EndAcquisition() 
tEndAcq = time.time()
print('Capture ends at: {:.2f}sec'.format(tEndAcq - tStart))
#   print('calculated frame rate: {:.2f}FPS'.format(numImages/(t2 - t1)))
image_queue.join() #wait until queue is done writing to disk
tEndWrite = time.time()
print('File written at: {:.2f}sec'.format(tEndWrite - tStart))
writer.close()
window.destroy()
    
# set camera back to default state and delete all pointers/varaiable/etc:
cam.UserSetSelector.SetValue(PySpin.UserSetSelector_Default)
cam.UserSetLoad()
del image
cam.DeInit()
del cam
cam_list.Clear()
del cam_list
system.ReleaseInstance()
del system
print('Done!')
