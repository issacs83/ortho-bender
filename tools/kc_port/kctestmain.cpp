/*
 * kctestmain.cpp - B2 test program (Linux port)
 * Original: YOAT Corporation B2 TEST PROGRAM v1.1
 * Changes: CAP_DSHOW→CAP_V4L2, Sleep→platform.h, QPC→chrono, exit()→std::exit()
 */
#include "stub.h"
#ifdef USE_CAMERA
#include <opencv2/opencv.hpp>
#include <opencv2/imgproc/types_c.h>
#endif
#include <iostream>
#include <thread>
#include <mutex>
#include <queue>
#include <atomic>
#include <cstdlib>
#include <cmath>

// USE_CAMERA and USE_MOTOR are defined by CMake (target_compile_definitions)

#ifdef USE_CAMERA
using namespace cv;
#endif
using namespace std;

#ifdef USE_CAMERA
std::queue<cv::Mat> g_camera_buffer;
std::mutex          g_camera_mtxCam;
std::atomic<bool>   g_camerathread_flag;
#endif
std::atomic<bool>   g_motorthread_flag;
#ifdef USE_CAMERA
std::thread*        m_pCamthread = NULL;
#endif
std::thread*        m_pMotorThread = NULL;


#ifdef USE_CAMERA
void GrabThread(cv::VideoCapture* cap)
{
    cv::Mat tmp;

    try
    {
        if (g_camerathread_flag.load())
            printf("* Start GrabThread()...\n");

        while (g_camerathread_flag.load() == true)
        {
            cap->read(tmp);

            if (tmp.empty())
                continue;

            g_camera_mtxCam.lock();
            g_camera_buffer.push(cv::Mat(tmp.size(), tmp.type()));
            tmp.copyTo(g_camera_buffer.back());
            g_camera_mtxCam.unlock();
        }
    }
    catch (...)
    {
        printf("* GrabThread() failed to run.\n");
        Sleep(5000);
        std::exit(-1);
    }

    printf("* Exit GrabThread()\n");
}
#endif


void MotorInitProc()
{
    printf("* Test lights...\n");
    printf(">\tVision Light On...\n");
    mlVisionLight(255);

    printf(">\tLogo Light soft blink R...\n");
    mlLogoLightBlinkSoft(2, 1, 10);
    printf(">\tLogo Light soft blink G...\n");
    mlLogoLightBlinkSoft(3, 1, 10);
    printf(">\tLogo Light soft blink B...\n");
    mlLogoLightBlinkSoft(4, 1, 10);

    printf(">\tLogo Light On...\n");
    mlLogoLightOn(1);

    mlLogoLightHeartbeatStart(2);

    printf("* Stop all motors...\n");
    mcStop(MID_CUTTER);
    mcStop(MID_BENDER);
    mcStop(MID_LIFTER);
    mcStop(MID_FEEDER);

    printf("* Setup all motor resolutions...\n");
    mcSetRes(MID_BENDER, 1);
    mcSetRes(MID_LIFTER, 1);
    mcSetRes(MID_CUTTER, 1);
    mcSetRes(MID_FEEDER, 1);

    printf("* Motor initialization...\n");
    printf(">\tInit bending motor...\n");
    mlInit(MID_BENDER);
    printf(">\tInit cutter motor...\n");
    mlInit(MID_CUTTER);
    printf(">\tInit feeder motor...\n");
    mlInit(MID_FEEDER);

    printf(">\tBending motor is in position...\n");
    mcInit(MID_BENDER, DIR_CW, 1000);
    if (E_TIMEOUT == mlWaitMotor(MID_BENDER, 5.0)) printf("[ERROR] mlWaitMotor (MID_BENDER)\n");

    printf(">\tCutter motor is in position...\n");
    mcInit(MID_CUTTER, DIR_CW, 1000);
    if (E_TIMEOUT == mlWaitMotor(MID_CUTTER, 5.0)) printf("[ERROR] mlWaitMotor (MID_CUTTER)\n");
    mcStop(MID_CUTTER);
    mcStop(MID_BENDER);

    printf(">\tRotates bending motor at 360 degrees...\n");
    mcMoveVel(MID_BENDER, DIR_CCW, DEG2STEP(360, MID_BENDER), 1000);

    printf("\t>\tIn-motion...");
    while (1)
    {
        if (false == mlInMotion(MID_BENDER))
            break;
        printf(".");
    }
    printf(".\n");

    mlLogoLightHeartbeatEnd();
}


void MotorBendingProc()
{
    while (g_motorthread_flag.load() == true)
    {
        printf("* Feeding...\n");
        mcMoveVel(MID_FEEDER, DIR_CCW, MM2STEP(1), 200);
        Sleep(100);
        mcStop(MID_FEEDER);

        if (!g_motorthread_flag.load()) break;

        printf("* Check Sensors: ");
        bool sensors[5] = { 0, };
        mcGetSensorState(sensors);
        printf("B=%d, F0=%d, F1=%d, R=%d, C=%d\n", sensors[0], sensors[1], sensors[2], sensors[3], sensors[4]);
        Sleep(500);

        if (!g_motorthread_flag.load()) break;

        for (int k = 0; k < 10; k++)
        {
            if (!g_motorthread_flag.load()) break;

            int pos = 0;
            mcGetPos(MID_BENDER, pos);
            printf("* Bending... (pos=%d, deg=%f)\n", pos, STEP2DEG(pos, MID_BENDER));
            mcMoveVel(MID_BENDER, (k % 2) == 0 ? DIR_CW : DIR_CCW, DEG2STEP(90, MID_BENDER), 1000);
            mlWaitMotor(MID_BENDER);

            mcStop(MID_BENDER);

            if (!IsCommConnected())
            {
                printf("[ERROR] Connection has been closed. Try to reconnect...\n");
                mcFindComm();
            }
        }

        if (!g_motorthread_flag.load()) break;

        printf("* Cutting...\n");
        mlInit(MID_CUTTER);
    }
}

void MotorThread()
{
    bool bConnected = mcFindComm();
    if (!bConnected)
    {
        printf("* Bender 2 not found.\n");
        std::exit(-1);
    }

    try
    {
        MotorInitProc();
        MotorBendingProc();
    }
    catch (int e)
    {
        printf("* Exception Code: %d\n", e);
    }
}

#ifdef USE_CAMERA
bool StartCamera(VideoCapture& cap)
{
    if (!cap.isOpened())
    {
        cout << "[ERROR] Cannot open the camera" << endl;
        return false;
    }

    cap.set(cv::CAP_PROP_FRAME_WIDTH, 640);
    cap.set(cv::CAP_PROP_FRAME_HEIGHT, 480);
    cap.set(cv::CAP_PROP_FPS, 30);
    cap.set(cv::CAP_PROP_EXPOSURE, -10);

    g_camerathread_flag.store(true);
    m_pCamthread = new std::thread(GrabThread, &cap);

    Sleep(500);

    return true;
}
#endif


int main(int argc, char* argv[])
{
    printf("\n****************************************************************\n");
    printf("* B2 TEST PROGRAM v1.1-linux (ported for i.MX8MP-EVK)         *\n");
    printf("* Original (c) Copyright 2022 by YOAT Corporation             *\n");
    printf("****************************************************************\n\n");

    QueryPerformanceFrequency(&g_frequency);

#ifdef USE_CAMERA
    int camIdx = 0;
    if (argc > 1)
    {
        camIdx = stoi(argv[1]);
    }

    VideoCapture cap;
#endif

#ifdef USE_CAMERA
    // Linux: use V4L2 backend instead of DirectShow
    cap.open(camIdx, cv::CAP_V4L2);
    if (!StartCamera(cap))
        return -1;
#endif

#ifdef USE_MOTOR
    g_motorthread_flag.store(true);
    m_pMotorThread = new std::thread(MotorThread);
#endif

#ifdef USE_CAMERA
    int m_iUncaptured = 0;

    cv::Mat capturedImageColor;

    while (1)
    {
        bool bCaptured = false;

        g_camera_mtxCam.lock();
        int bufSize = g_camera_buffer.size();
        if (bufSize > 0)
        {
            g_camera_buffer.back().copyTo(capturedImageColor);
            g_camera_buffer = {};
            bCaptured = true;
        }
        g_camera_mtxCam.unlock();

        cv::Mat capturedImageGray;

        if (bCaptured)
        {
            cv::cvtColor(capturedImageColor, capturedImageGray, cv::COLOR_RGB2GRAY);
            imshow("Bender 2 Vision", capturedImageGray);

            auto result = cv::mean(capturedImageGray);
            float Brightness = result[0];

            uint8_t* pImageBuffer = (uint8_t*)capturedImageGray.data;
            int pixeltest = 0;
            const int pxoffset = (480 / 2) * 640;
            for (int k = 0; k < 480; k++)
            {
                if (pImageBuffer[pxoffset] == pImageBuffer[pxoffset + k])
                    pixeltest++;
                else
                    break;
            }

            if (pixeltest > 400 || capturedImageColor.empty() || fabs(Brightness) < 0.00001f)
            {
                bCaptured = false;
                m_iUncaptured++;
            }
        }
        else
        {
            m_iUncaptured++;
        }

        if (m_iUncaptured > 10)
        {
            m_iUncaptured = 0;
            cap.release();
            printf("[ERROR] Camera not working. Try to reconnect...\n");
            g_camerathread_flag.store(false);
            Sleep(2000);

            cap.open(camIdx, cv::CAP_V4L2);
            StartCamera(cap);
            continue;
        }

        Sleep(60);

        if (!bCaptured) continue;

        m_iUncaptured = 0;

        if (waitKey(5) >= 0)
        {
            printf("* Bender 2 Test stopping...\n");
            break;
        }
    }
#else
    {
        printf("* Motor Test Only. Press Enter to exit.\n");
        getchar();
    }
#endif

#ifdef USE_MOTOR
    mlVisionLight(0);
    mlLogoLightOff(1);
    g_motorthread_flag.store(false);
#endif

#ifdef USE_CAMERA
    cap.release();
    destroyAllWindows();
#endif

    return 0;
}
