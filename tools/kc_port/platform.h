/*
 * platform.h - Windows to Linux platform abstraction layer
 * Ortho-Bender kc_test port: minimal changes for i.MX8MP-EVK testing
 */
#pragma once

#include <chrono>
#include <thread>
#include <cstdio>
#include <cstdint>
#include <cstring>

// Replace Windows Sleep(ms)
inline void Sleep(unsigned int ms)
{
    std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

// Replace Windows LARGE_INTEGER + QueryPerformanceCounter/Frequency
struct PerfTimer {
    std::chrono::steady_clock::time_point point;
};

using LARGE_INTEGER = PerfTimer;

inline void QueryPerformanceFrequency(LARGE_INTEGER* /*freq*/)
{
    // No-op: chrono handles frequency internally
}

inline void QueryPerformanceCounter(LARGE_INTEGER* li)
{
    li->point = std::chrono::steady_clock::now();
}

// Elapsed seconds between two LARGE_INTEGER values
inline double PerfElapsedSec(const LARGE_INTEGER& start, const LARGE_INTEGER& end)
{
    auto dur = end.point - start.point;
    return std::chrono::duration<double>(dur).count();
}

// Replace sprintf_s with snprintf
#define sprintf_s snprintf
