// SPDX-License-Identifier: Apache-2.0
//
// Wrap Samsung libsec-ril*.so, force NULL SMSC only for legacy CS SMS
// requests, and normalize packed data-call MTUs. IMS SMS is intentionally
// left untouched.

#include <dlfcn.h>
#include <stdint.h>
#include <string.h>

#include <atomic>
#include <mutex>
#include <unordered_map>
#include <vector>

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
static RIL_RequestFunc gReal_onRequest = nullptr;
static RIL_Env gOriginalEnv = {};
static RIL_Env gShimEnv = {};
static std::atomic_bool gSupportsDataCallResponseV11{false};
static std::mutex gPendingRequestsMutex;
static std::unordered_map<RIL_Token, int> gPendingRequests;

static constexpr int kNoPendingRequest = -1;
static constexpr uint32_t kMinimumPlausibleMtu = 576;
static constexpr uint32_t kMaximumPlausibleMtu = 10000;

static bool isCsSmsRequest(int request) {
    return request == RIL_REQUEST_SEND_SMS ||
           request == RIL_REQUEST_SEND_SMS_EXPECT_MORE;
}

static bool isDataCallRequest(int request) {
    return request == RIL_REQUEST_SETUP_DATA_CALL ||
           request == RIL_REQUEST_DATA_CALL_LIST;
}

static int normalizePackedMtu(int mtu) {
    if (mtu <= 0xffff) {
        return mtu;
    }

    const uint32_t rawMtu = static_cast<uint32_t>(mtu);
    const uint32_t upperMtu = rawMtu >> 16;
    const uint32_t lowerMtu = rawMtu & 0xffff;

    if (upperMtu >= kMinimumPlausibleMtu &&
            upperMtu <= kMaximumPlausibleMtu &&
            lowerMtu >= kMinimumPlausibleMtu &&
            lowerMtu <= kMaximumPlausibleMtu) {
        return static_cast<int>(upperMtu < lowerMtu ? upperMtu : lowerMtu);
    }

    return mtu;
}

static bool normalizeDataCallResponses(
        const void* data, size_t datalen,
        std::vector<RIL_Data_Call_Response_v11>* normalizedResponses) {
    if (data == nullptr || datalen == 0 ||
            datalen % sizeof(RIL_Data_Call_Response_v11) != 0) {
        return false;
    }

    const size_t responseCount = datalen / sizeof(RIL_Data_Call_Response_v11);
    normalizedResponses->resize(responseCount);
    memcpy(normalizedResponses->data(), data, datalen);

    bool changed = false;
    for (RIL_Data_Call_Response_v11& response : *normalizedResponses) {
        const int originalMtu = response.mtu;
        response.mtu = normalizePackedMtu(originalMtu);

        if (response.mtu != originalMtu) {
            ALOGI("sec-ril-smsc-shim: data call cid=%d: normalized packed MTU %d to %d",
                  response.cid, originalMtu, response.mtu);
            changed = true;
        }
    }

    return changed;
}

static void rememberPendingRequest(RIL_Token token, int request) {
    std::lock_guard<std::mutex> lock(gPendingRequestsMutex);
    gPendingRequests[token] = request;
}

static int takePendingRequest(RIL_Token token) {
    std::lock_guard<std::mutex> lock(gPendingRequestsMutex);
    const auto it = gPendingRequests.find(token);
    if (it == gPendingRequests.end()) {
        return kNoPendingRequest;
    }

    const int request = it->second;
    gPendingRequests.erase(it);
    return request;
}

static void Shim_OnRequestComplete(
        RIL_Token token, RIL_Errno error, void* response, size_t responselen) {
    const int request = takePendingRequest(token);

    if (gSupportsDataCallResponseV11.load() && error == RIL_E_SUCCESS &&
            isDataCallRequest(request)) {
        std::vector<RIL_Data_Call_Response_v11> normalizedResponses;
        if (normalizeDataCallResponses(response, responselen, &normalizedResponses)) {
            gOriginalEnv.OnRequestComplete(
                    token, error, normalizedResponses.data(), responselen);
            return;
        }
    }

    gOriginalEnv.OnRequestComplete(token, error, response, responselen);
}

#if defined(ANDROID_MULTI_SIM)
static void Shim_OnUnsolicitedResponse(
        int unsolResponse, const void* data, size_t datalen, RIL_SOCKET_ID socketId) {
    if (gSupportsDataCallResponseV11.load() &&
            unsolResponse == RIL_UNSOL_DATA_CALL_LIST_CHANGED) {
        std::vector<RIL_Data_Call_Response_v11> normalizedResponses;
        if (normalizeDataCallResponses(data, datalen, &normalizedResponses)) {
            gOriginalEnv.OnUnsolicitedResponse(
                    unsolResponse, normalizedResponses.data(), datalen, socketId);
            return;
        }
    }

    gOriginalEnv.OnUnsolicitedResponse(unsolResponse, data, datalen, socketId);
}
#else
static void Shim_OnUnsolicitedResponse(
        int unsolResponse, const void* data, size_t datalen) {
    if (gSupportsDataCallResponseV11.load() &&
            unsolResponse == RIL_UNSOL_DATA_CALL_LIST_CHANGED) {
        std::vector<RIL_Data_Call_Response_v11> normalizedResponses;
        if (normalizeDataCallResponses(data, datalen, &normalizedResponses)) {
            gOriginalEnv.OnUnsolicitedResponse(
                    unsolResponse, normalizedResponses.data(), datalen);
            return;
        }
    }

    gOriginalEnv.OnUnsolicitedResponse(unsolResponse, data, datalen);
}
#endif

static void callRealOnRequest(
        int request, void* data, size_t datalen, RIL_Token token,
        RIL_SOCKET_ID socketId) {
#if defined(ANDROID_MULTI_SIM)
    gReal_onRequest(request, data, datalen, token, socketId);
#else
    (void)socketId;
    gReal_onRequest(request, data, datalen, token);
#endif
}

static void Shim_onRequestInternal(
        int request, void* data, size_t datalen, RIL_Token token,
        RIL_SOCKET_ID socketId) {
    if (isDataCallRequest(request)) {
        rememberPendingRequest(token, request);
    }

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

            callRealOnRequest(request, const_cast<char**>(fixedSmsData),
                              sizeof(fixedSmsData), token, socketId);
            return;
        }

        ALOGW("sec-ril-smsc-shim: request %d: CS SMS request has null PDU; forwarding unchanged",
              request);
    }

    callRealOnRequest(request, data, datalen, token, socketId);
}

#if defined(ANDROID_MULTI_SIM)
static void Shim_onRequest(
        int request, void* data, size_t datalen, RIL_Token token,
        RIL_SOCKET_ID socketId) {
    Shim_onRequestInternal(request, data, datalen, token, socketId);
}
#else
static void Shim_onRequest(int request, void* data, size_t datalen, RIL_Token token) {
    Shim_onRequestInternal(request, data, datalen, token, RIL_SOCKET_1);
}
#endif

extern "C"
const RIL_RadioFunctions* RIL_Init(const RIL_Env* env, int argc, char** argv) {
    ALOGI("sec-ril-smsc-shim: loading real RIL from %s", kRealPath);

    if (env == nullptr || env->OnRequestComplete == nullptr ||
            env->OnUnsolicitedResponse == nullptr) {
        ALOGE("sec-ril-smsc-shim: invalid RIL environment");
        return nullptr;
    }

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

    gOriginalEnv = *env;
    gShimEnv = *env;
    gShimEnv.OnRequestComplete = Shim_OnRequestComplete;
    gShimEnv.OnUnsolicitedResponse = Shim_OnUnsolicitedResponse;

    const RIL_RadioFunctions* real = gReal_RIL_Init(&gShimEnv, argc, argv);
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

    gSupportsDataCallResponseV11.store(real->version >= 12);
    gReal_onRequest = real->onRequest;
    sShimFunctions.onRequest = Shim_onRequest;

    ALOGI("sec-ril-smsc-shim: installed CS SMSC and data-call MTU shim for %s",
          REAL_LIB_NAME);
    return &sShimFunctions;
}
