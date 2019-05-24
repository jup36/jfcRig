# -*- coding: utf-8 -*-
# Jason Keller
# May 2019
# =============================================================================
#  Program to set BlackFly S camera settings and acquire frames and write them
#  to a compressed video file. Based on FLIR Spinnaker 'Acquisition', 'Enumeration',
#  and 'CounterAndTimer' (see these for API details), and example code from:
#  https://www.jianshu.com/p/e12a5521bdd2
# 
#  The intent is that DAQ is started first, then this program will start
#  the camera with a software trigger and output ExposureActive signal on Line 1
#  (DAQ should sample this at 5kHz+) so that each frame can be synchronized. 
#
#  Tkinter is used to provide a simple GUI to start / stop acquisition, and 
#  numpy and tifffile are used to write data to disk in zlib lossless compressed 
#  bigTif format
#
# TO DO:
# (1) report # missed / delayed frames somehow? (maybe use counter to count Line 1 edges and write to video file)
# (2) 
# =============================================================================

# NOTE that from the penultimate image grab until now will take a few milliseconds,
# so the last AcquisitionActive edges can be discarded by the DAQ system

import PySpin, time, threading, queue, os 
#import tifffile #only for writing to TIF
import numpy as np
import skvideo
skvideo.setFFmpegPath('C:/Anaconda3/Lib/site-packages/ffmpeg') #set path to ffmpeg installation before importing io
import skvideo.io

#constants
SAVE_FOLDER = 'C:/video/test'
#TIFNAME = 'test.tif' #btf for bigTif
MOVNAME = 'test.mp4' #always AVI file, but has H264 compression
EXPOSURE_TIME = 2150 # in microseconds; this determines frame rate
GAIN_VALUE = 25 #in dB, 0-40
NUM_IMAGES = 10

if not os.path.exists(SAVE_FOLDER):
    os.mkdir(SAVE_FOLDER)
os.chdir(SAVE_FOLDER)

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

def save_img(image_queue, writer, i):
#    filename = 'Acquisition%d.tif' % i
###    image.Save(filename)
##    arrayToWrite = image.GetNDArray()
    while True:
        dequeuedImage = image_queue.get() 
        #make pointer to image (for SpinVideo )
        if dequeuedImage is None:
            break
        else:
            # option to write to bigTif stack: note that even when compressed, this takes longer and is less efficient
#            with tifffile.TiffWriter(TIFNAME, append=True, bigtiff=False) as tif: # bigtiff=True
#                tif.save(dequeuedImage, compress=0) #uncompressed for speed; ZLIB compress=6 is tradeoff between speed and compression level
            writer.writeFrame(dequeuedImage)
#            if i%10 == 0: #aslo update screen every X frames
#                plt.imshow(dequeuedImage)
#                plt.show()
#                cv2.imshow('Frame', dequeuedImage)
            image_queue.task_done()

# setup output video file parameters (can try H265 in future for better compression):
# framerate does not seem to work without adding extra frames, so just accept default 25fps output and change elsewhere if needed            
crfOut = 25 #controls tradeoff between quality and storage, see https://trac.ffmpeg.org/wiki/Encode/H.264 
writer = skvideo.io.FFmpegWriter(MOVNAME, outputdict={'-vcodec': 'libx264', '-crf' : str(crfOut)})

#setup tkinter GUI (non-blocking) to output images to screen quickly


#############################################################################
# start main program ########################################################
#############################################################################    

try:
    print('Video will be saved to: {}'.format(SAVE_FOLDER))
    cam.BeginAcquisition()
    t1 = time.time()
    i = 0
    image_queue = queue.Queue() #create queue in memory to store images while asynchronously written to disk
    # setup another thread to accelerate saving, and start immediately:
    save_thread = threading.Thread(target=save_img, args=(image_queue, writer, i,))
    save_thread.start()  

    for i in range(NUM_IMAGES):
#    while True:
#        print(i)
        image = cam.GetNextImage() #get pointer to next image in camera buffer; blocks until image arrives via USB; timeout=INF 
#        if image.IsIncomplete():
#            print('Image incomplete with image status {} ...'.format(image.GetImageStatus()))
        enqueuedImage = np.array(image.GetData(), dtype="uint8").reshape( (image.GetHeight(), image.GetWidth()) ); #convert PySpin ImagePtr into numpy array
        image_queue.put(enqueuedImage) #put next image in queue

        image.Release() #release from camera buffer
#        i += 1
#        frameNum = cam.EventExposureEndFrameID
#        print(frameNum)
            
    # NOTE that from the penultimate image grab until EndAcquisition to stop Line 1 will take a few milliseconds,
    # so the last AcquisitionActive edges can be discarded by the DAQ system
    cam.EndAcquisition() 
    t2 = time.time()
    print('Capturing time: {:.2f}s'.format(t2 - t1))
    print('AcquisitionResultingFrameRate: {:.2f}FPS'.format(cam.AcquisitionResultingFrameRate()))
#   print('calculated frame rate: {:.2f}FPS'.format(NUM_IMAGES/(t2 - t1)))
    image_queue.join() #wait until queue is done writing to disk
    t3 = time.time()
    print('Writing time: {:.2f}s'.format(t3 - t1))
    writer.close()
#    plt.close(1)
    print('Saved: %s' % MOVNAME)
    
except KeyboardInterrupt:
    pass

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
