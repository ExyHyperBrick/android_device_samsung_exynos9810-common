// SPDX-License-Identifier: Apache-2.0
//
// Wrap Samsung libsec-ril*.so and force NULL SMSC only for legacy CS SMS
// requests. IMS SMS is intentionally left untouched.

#include <dlfcn.h>
#include <string.h>

#include <log/log.h>
#include <telephony/ril.h>

#ifndef REAL_LIB_NAME
#error "REAL_LIB_NAME must be defined by Android.bp, e.g. libsec-ril-impl.so"
#endif

#ifndef RIL_REQUEST_SEND_SMS
#define RIL_REQUEST_SEND_SMS 25
#endif

#ifndef RIL_REQUEST_SEND_SMS_EXPECT_MORE
#define RIL_REQUEST_SEND_SMS_EXPECT_MORE 26
#endif

static const char* kRealPath = "/vendor/lib64/" REAL_LIB_NAME;

static void* gRealHandle = nullptr;
static const RIL_RadioFunctions* (*gReal_RIL_Init)(const RIL_Env*, int, char**) = nullptr;
static void (*gReal_onRequest)(int, void*, size_t, RIL_Token) = nullptr;

static bool isCsSmsRequest(int request) {
    return request == RIL_REQUEST_SEND_SMS ||
           request == RIL_REQUEST_SEND_SMS_EXPECT_MORE;
}

static void Shim_onRequest(int request, void* data, size_t datalen, RIL_Token token) {
    if (isCsSmsRequest(request) && data != nullptr && datalen >= 2 * sizeof(char*)) {
        const char** smsData = static_cast<const char**>(data);
        const char* smsc = smsData[0];
        const char* pdu = smsData[1];

        if (pdu != nullptr) {
            const char* fixedSmsData[2] = {
                nullptr, // SMSC: force NULL only for legacy CS SMS
                pdu,
            };

            ALOGI("sec-ril-smsc-shim: request %d: forcing CS SMSC NULL, original smsc=%s",
                  request, smsc != nullptr ? smsc : "null");

            gReal_onRequest(request, const_cast<char**>(fixedSmsData), sizeof(fixedSmsData), token);
            return;
        }

        ALOGW("sec-ril-smsc-shim: request %d: CS SMS request has null PDU; forwarding unchanged",
              request);
    }

    gReal_onRequest(request, data, datalen, token);
}

extern "C"
const RIL_RadioFunctions* RIL_Init(const RIL_Env* env, int argc, char** argv) {
    ALOGI("sec-ril-smsc-shim: loading real RIL from %s", kRealPath);

    gRealHandle = dlopen(kRealPath, RTLD_NOW);
    if (gRealHandle == nullptr) {
        ALOGE("sec-ril-smsc-shim: dlopen(%s) failed: %s", kRealPath, dlerror());
        return nullptr;
    }

    gReal_RIL_Init = reinterpret_cast<decltype(gReal_RIL_Init)>(dlsym(gRealHandle, "RIL_Init"));
    if (gReal_RIL_Init == nullptr) {
        ALOGE("sec-ril-smsc-shim: dlsym(RIL_Init) failed: %s", dlerror());
        return nullptr;
    }

    const RIL_RadioFunctions* real = gReal_RIL_Init(env, argc, argv);
    if (real == nullptr) {
        ALOGE("sec-ril-smsc-shim: real RIL_Init returned null");
        return nullptr;
    }

    if (real->onRequest == nullptr) {
        ALOGE("sec-ril-smsc-shim: real RIL function table has null onRequest");
        return real;
    }

    static RIL_RadioFunctions sShimFunctions;
    sShimFunctions = *real;

    gReal_onRequest = real->onRequest;
    sShimFunctions.onRequest = Shim_onRequest;

    ALOGI("sec-ril-smsc-shim: installed CS SMSC NULL shim for %s", REAL_LIB_NAME);
    return &sShimFunctions;
}
