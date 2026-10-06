/*
 * SPDX-FileCopyrightText: The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 *
 * Derived from LineageOS/android_hardware_samsung soundbooster at
 * 5d20e3541d147494e074bf710d35b1960a6ed0a2. The adapter is deliberately
 * limited to the stock S9/S9+ ver900 and Note9 ver950 named-method ABI.
 */

#pragma once

#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <log/log.h>

enum BitDepth {
    BIT_DEPTH_NONE = 0,  // interleaved signed PCM16
    BIT_DEPTH_FLOAT = 3,
};

// Resolve named methods from one explicitly loaded library. This avoids relying
// on different Samsung generations' incompatible C++ virtual table layouts.
class SoundBoosterInterface {
  public:
    SoundBoosterInterface() = default;
    ~SoundBoosterInterface() {
        if (mInstance != nullptr && mDestroy != nullptr) mDestroy(mInstance);
        if (mLibrary != nullptr) dlclose(mLibrary);
    }
    SoundBoosterInterface(const SoundBoosterInterface&) = delete;
    SoundBoosterInterface& operator=(const SoundBoosterInterface&) = delete;

    int open() {
        if (mInstance != nullptr) return 0;
        if (mLibrary == nullptr) {
            const auto load = [this](const char* name, int version) {
                mLibrary = dlopen(name, RTLD_NOW | RTLD_LOCAL);
                if (mLibrary == nullptr) {
                    // Capture this attempt before another dlopen overwrites dlerror().
                    const char* error = dlerror();
                    ALOGW("Cannot load stock SoundBooster ver%d (%s): %s", version, name,
                          error != nullptr ? error : "unknown loader error");
                    return false;
                }
                mVersion = version;
                ALOGI("Loaded stock SoundBooster ver%d (%s)", version, name);
                return true;
            };
            if (!load("lib_SoundBooster_ver900.so", 900) &&
                !load("lib_SoundBooster_ver950.so", 950)) {
                ALOGE("No stock SoundBooster DSP could be loaded");
                return -ENODEV;
            }
        }
        if (!resolve(mCreate, "_ZN30SoundBooster_Interface_Factory6CreateEi") ||
            !resolve(mDestroy,
                     "_ZN30SoundBooster_Interface_Factory7DestroyEP25SoundBooster_Interface_IF") ||
            !resolve(mInit, "_ZN22SoundBooster_Interface4InitE13SB_BitDepth_T") ||
            !resolve(mRate, "_ZN22SoundBooster_Interface18SamplingRateConfigEi") ||
            !resolve(mLoad, "_ZN22SoundBooster_Interface13LoadParameterEPKcbPf") ||
            !resolve(mMotion, "_ZN22SoundBooster_Interface9SetMotionEi") ||
            !resolve(mOrientation,
                     "_ZN22SoundBooster_Interface14SetOrientationE23SB_Device_Orientation_T") ||
            !resolve(mClear, "_ZN22SoundBooster_Interface9BuffClearEv") ||
            !resolve(mProcess, "_ZN22SoundBooster_Interface3ExeEPvPKvif")) {
            return -ENOSYS;
        }
        mInstance = mCreate(2);  // stock speaker mode
        if (mInstance == nullptr) return -ENOMEM;
        return 0;
    }

    int version() const { return mVersion; }
    int init(BitDepth depth, int rate, const char* path, float* volumeTable) {
        if (mInstance == nullptr) return -ENODEV;
        int result = status(mInit(mInstance, depth));
        if (result == 0) result = status(mRate(mInstance, rate));
        if (result == 0) result = status(mLoad(mInstance, path, false, volumeTable));
        return result;
    }
    int load(const char* path, float* volumeTable) {
        return mInstance == nullptr ? -ENODEV : status(mLoad(mInstance, path, false, volumeTable));
    }
    int clear() { return mInstance == nullptr ? -ENODEV : status(mClear(mInstance)); }
    int motion(int flat) {
        return mInstance == nullptr ? -ENODEV : status(mMotion(mInstance, flat));
    }
    int orientation(int rotation) {
        // Stock wrapper reverses the two landscape orientations.
        if (rotation == 1) rotation = 3;
        else if (rotation == 3) rotation = 1;
        return mInstance == nullptr ? -ENODEV : status(mOrientation(mInstance, rotation));
    }
    int process(void* samples, int frames, float volumeDb) {
        if (mInstance == nullptr) return -ENODEV;
        // Exact ver900/ver950 returns frames, rather than zero, on successful Exe().
        const int result = mProcess(mInstance, samples, samples, frames, volumeDb);
        return result == frames ? 0 : result < 0 ? result : -EIO;
    }

  private:
    template <typename T> bool resolve(T& method, const char* name) {
        method = reinterpret_cast<T>(dlsym(mLibrary, name));
        if (method == nullptr) ALOGE("Missing stock SoundBooster ABI symbol: %s", name);
        return method != nullptr;
    }
    static int status(int result) { return result <= 0 ? result : -EIO; }
    using Create = void* (*)(int);
    using Destroy = void (*)(void*);
    using Init = int (*)(void*, BitDepth);
    using Integer = int (*)(void*, int);
    using Load = int (*)(void*, const char*, bool, float*);
    using Clear = int (*)(void*);
    using Process = int (*)(void*, void*, const void*, int, float);
    int mVersion = 0;
    void* mLibrary = nullptr;
    void* mInstance = nullptr;
    Create mCreate = nullptr;
    Destroy mDestroy = nullptr;
    Init mInit = nullptr;
    Integer mRate = nullptr;
    Load mLoad = nullptr;
    Integer mMotion = nullptr;
    Integer mOrientation = nullptr;
    Clear mClear = nullptr;
    Process mProcess = nullptr;
};
