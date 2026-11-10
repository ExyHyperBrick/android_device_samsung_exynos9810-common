/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

//
// Wrap Samsung libsec-ril*.so and normalize non-standard modem responses.

#include <dlfcn.h>
#include <string.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include <log/log.h>
#include <telephony/ril.h>

#ifndef REAL_LIB_NAME
#error "REAL_LIB_NAME must be defined by Android.bp, e.g. libsec-ril-impl.so"
#endif

#ifndef RIL_REQUEST_GET_SMSC_ADDRESS
#define RIL_REQUEST_GET_SMSC_ADDRESS 100
#endif

static const char* kRealPath = "/vendor/lib64/" REAL_LIB_NAME;

static void* gRealHandle = nullptr;
static const RIL_RadioFunctions* (*gReal_RIL_Init)(const RIL_Env*, int, char**) = nullptr;
static void (*gReal_onRequest)(int, void*, size_t, RIL_Token) = nullptr;

static RIL_Env gShimEnv;
static const RIL_Env* gRealEnv = nullptr;

static std::mutex gRequestMutex;
static std::unordered_map<RIL_Token, int> gRequests;
static std::atomic<int> gRilVersion{0};

// Samsung's LP64 v12 response retains the v11 scalar MTU, followed by
// IPv4 and IPv6 MTUs. Keep the complete record, including its tail padding.
static constexpr size_t kSamsungDataCallSize = 80;
static constexpr size_t kSamsungMtuV4Offset = 68;
static constexpr size_t kSamsungMtuV6Offset = 72;
static_assert(sizeof(RIL_Data_Call_Response_v11) == 72);
static_assert(offsetof(RIL_Data_Call_Response_v11, mtu) == 64);
static_assert(sizeof(int) == 4);

static int minimumDataCallMtu(const char* type) {
    if (type == nullptr) return 0;
    if (strcmp(type, "IP") == 0) return 68;
    if (strcmp(type, "IPV6") == 0 || strcmp(type, "IPV4V6") == 0) return 1280;
    return 0;
}

static int normalizeDataCallMtu(const RIL_Data_Call_Response_v11& call) {
    if (call.status != 0 || call.mtu <= 0xffff) return call.mtu;

    int minimum = minimumDataCallMtu(call.type);
    if (minimum == 0) return call.mtu;

    // Preserve support for legacy responses containing two packed MTUs.
    uint32_t packed = static_cast<uint32_t>(call.mtu);
    int low = packed & 0xffff;
    int high = packed >> 16;
    if (low < minimum || high < minimum) return call.mtu;
    return std::min(low, high);
}

static bool normalizeDataCalls(const void* response, size_t responselen, bool setup,
                               std::vector<uint64_t>* normalized) {
    int version = gRilVersion.load(std::memory_order_acquire);
    if (version < 11 || version > 15 || response == nullptr || responselen == 0) {
        return false;
    }

    bool legacy = responselen % sizeof(RIL_Data_Call_Response_v11) == 0;
    bool samsung = version == 15 && responselen % kSamsungDataCallSize == 0;
    // A list length divisible by both sizes does not identify its record layout.
    if (legacy == samsung) return false;
    size_t recordSize = samsung ? kSamsungDataCallSize : sizeof(RIL_Data_Call_Response_v11);
    if (setup && responselen != recordSize) return false;

    const auto* bytes = static_cast<const unsigned char*>(response);
    size_t count = responselen / recordSize;
    for (size_t i = 0; i < count; ++i) {
        const auto* record = bytes + i * recordSize;
        RIL_Data_Call_Response_v11 call;
        memcpy(&call, record, sizeof(call));

        int mtu;
        if (samsung) {
            if (call.status != 0 || call.mtu < 68 || call.mtu > 0xffff) continue;
            int minimum = minimumDataCallMtu(call.type);
            if (minimum == 0 || call.mtu < minimum) continue;
            // The vendor already calculated a scalar MTU. Its HIDL 1.4 bridge
            // packs the per-family fields again, so clear that upper half only
            // in the forwarded copy. The vendor-owned response stays unchanged.
            mtu = call.mtu;
            int mtuV4, mtuV6;
            memcpy(&mtuV4, record + kSamsungMtuV4Offset, sizeof(mtuV4));
            memcpy(&mtuV6, record + kSamsungMtuV6Offset, sizeof(mtuV6));
            if (mtuV4 == mtu && mtuV6 == 0) continue;
        } else {
            mtu = normalizeDataCallMtu(call);
            if (mtu == call.mtu) continue;
        }

        if (normalized->empty()) {
            // Both known LP64 record sizes are multiples of eight. Word storage
            // keeps the copy suitably aligned for the vendor callback consumer.
            normalized->resize(responselen / sizeof(uint64_t));
            memcpy(normalized->data(), response, responselen);
        }
        auto* output = reinterpret_cast<unsigned char*>(normalized->data()) + i * recordSize;
        size_t mtuOffset = samsung ? kSamsungMtuV4Offset : offsetof(RIL_Data_Call_Response_v11, mtu);
        memcpy(output + mtuOffset, &mtu, sizeof(mtu));
        if (samsung) {
            int zero = 0;
            memcpy(output + kSamsungMtuV6Offset, &zero, sizeof(zero));
        }
    }
    return !normalized->empty();
}

static int hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int parseHexByte(const std::string& value, size_t offset) {
    if (offset + 2 > value.size()) return -1;

    int high = hexNibble(value[offset]);
    int low = hexNibble(value[offset + 1]);
    if (high < 0 || low < 0) return -1;

    return (high << 4) | low;
}

static int parseDecimalToa(const std::string& value, size_t offset) {
    while (offset < value.size() && (value[offset] == ' ' || value[offset] == '\t')) {
        ++offset;
    }

    int toa = 0;
    bool hasDigit = false;
    while (offset < value.size() && value[offset] >= '0' && value[offset] <= '9') {
        hasDigit = true;
        toa = toa * 10 + (value[offset] - '0');
        if (toa > 255) return -1;
        ++offset;
    }

    while (offset < value.size() && (value[offset] == ' ' || value[offset] == '\t')) {
        ++offset;
    }

    return hasDigit && offset == value.size() ? toa : -1;
}

static bool isDecimalNumber(const std::string& value, size_t offset = 0) {
    if (offset >= value.size()) return false;

    for (size_t i = offset; i < value.size(); ++i) {
        if (value[i] < '0' || value[i] > '9') return false;
    }
    return true;
}

static bool useInternationalTon(int toa) {
    if (toa < 0) {
        // Samsung commonly drops the international TON while keeping the
        // country-code-prefixed digits. Match the ImsStack normalization.
        return true;
    }

    if ((toa & 0x80) == 0) return false;

    int ton = toa & 0x70;
    return ton == 0x00 || ton == 0x10;
}

static bool decodeScaPdu(const std::string& pdu, std::string* number, int* toa) {
    if (pdu.size() < 6 || (pdu.size() & 1) != 0) return false;

    int addressLength = parseHexByte(pdu, 0);
    if (addressLength < 2) return false;

    size_t expectedLength = static_cast<size_t>(addressLength + 1) * 2;
    if (expectedLength != pdu.size()) return false;

    int addressToa = parseHexByte(pdu, 2);
    if (addressToa < 0 || (addressToa & 0x80) == 0) return false;

    // Alphanumeric TON is not semi-octet encoded as a normal phone number.
    if ((addressToa & 0x70) == 0x50) return false;

    std::string decoded;
    for (size_t i = 4; i < expectedLength; i += 2) {
        int octet = parseHexByte(pdu, i);
        if (octet < 0) return false;

        int low = octet & 0x0f;
        int high = (octet >> 4) & 0x0f;

        if (low > 9) return false;
        decoded += static_cast<char>('0' + low);

        if (high <= 9) {
            decoded += static_cast<char>('0' + high);
        } else if (high != 0x0f || i + 2 != expectedLength) {
            return false;
        }
    }

    if (decoded.empty()) return false;

    *number = decoded;
    *toa = addressToa;
    return true;
}

static std::string normalizeSmscAddress(const std::string& original) {
    std::string address = original;
    int toa = -1;

    size_t firstQuote = original.find('"');
    if (firstQuote != std::string::npos) {
        size_t secondQuote = original.find('"', firstQuote + 1);
        if (secondQuote == std::string::npos) return original;

        address = original.substr(firstQuote + 1, secondQuote - firstQuote - 1);

        size_t comma = original.find(',', secondQuote + 1);
        if (comma != std::string::npos) {
            toa = parseDecimalToa(original, comma + 1);
        }
    } else {
        size_t comma = original.find(',');
        if (comma != std::string::npos) {
            address = original.substr(0, comma);
            toa = parseDecimalToa(original, comma + 1);
        }
    }

    std::string decoded;
    int pduToa = -1;
    if (decodeScaPdu(address, &decoded, &pduToa)) {
        return useInternationalTon(pduToa) ? "+" + decoded : decoded;
    }

    if (!address.empty() && address[0] == '+' && isDecimalNumber(address, 1)) {
        return address;
    }

    if (isDecimalNumber(address)) {
        return useInternationalTon(toa) ? "+" + address : address;
    }

    return original;
}

static void Shim_OnRequestComplete(RIL_Token token, RIL_Errno error, void* response,
                                   size_t responselen) {
    int request = 0;
    {
        std::lock_guard<std::mutex> lock(gRequestMutex);
        auto it = gRequests.find(token);
        if (it != gRequests.end()) {
            request = it->second;
            gRequests.erase(it);
        }
    }

    if (error == RIL_E_SUCCESS && (request == RIL_REQUEST_SETUP_DATA_CALL
            || request == RIL_REQUEST_DATA_CALL_LIST)) {
        std::vector<uint64_t> normalized;
        if (normalizeDataCalls(response, responselen, request == RIL_REQUEST_SETUP_DATA_CALL,
                               &normalized)) {
            gRealEnv->OnRequestComplete(token, error, normalized.data(), responselen);
            return;
        }
    }

    if (request == RIL_REQUEST_GET_SMSC_ADDRESS && error == RIL_E_SUCCESS
            && response != nullptr && responselen > 0) {
        const char* original = static_cast<const char*>(response);
        std::string normalized = normalizeSmscAddress(original);

        if (normalized != original) {
            ALOGI("sec-ril-smsc-shim: normalized GET_SMSC_ADDRESS: %s -> %s",
                  original, normalized.c_str());
            gRealEnv->OnRequestComplete(token, error, const_cast<char*>(normalized.c_str()),
                                        normalized.size() + 1);
            return;
        }
    }

    gRealEnv->OnRequestComplete(token, error, response, responselen);
}

static void Shim_OnUnsolicitedResponse(int unsol, const void* response, size_t responselen) {
    if (unsol == RIL_UNSOL_DATA_CALL_LIST_CHANGED) {
        std::vector<uint64_t> normalized;
        if (normalizeDataCalls(response, responselen, false, &normalized)) {
            gRealEnv->OnUnsolicitedResponse(unsol, normalized.data(), responselen);
            return;
        }
    }
    gRealEnv->OnUnsolicitedResponse(unsol, response, responselen);
}

static void Shim_onRequest(int request, void* data, size_t datalen, RIL_Token token) {
    {
        std::lock_guard<std::mutex> lock(gRequestMutex);
        if (request == RIL_REQUEST_GET_SMSC_ADDRESS || request == RIL_REQUEST_SETUP_DATA_CALL
                || request == RIL_REQUEST_DATA_CALL_LIST) {
            gRequests[token] = request;
        } else {
            gRequests.erase(token);
        }
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

    gRealEnv = env;
    gShimEnv = *env;
    gShimEnv.OnRequestComplete = Shim_OnRequestComplete;
    gShimEnv.OnUnsolicitedResponse = Shim_OnUnsolicitedResponse;

    const RIL_RadioFunctions* real = gReal_RIL_Init(&gShimEnv, argc, argv);
    if (real == nullptr) {
        ALOGE("sec-ril-smsc-shim: real RIL_Init returned null");
        return nullptr;
    }
    gRilVersion.store(real->version, std::memory_order_release);

    if (real->onRequest == nullptr) {
        ALOGE("sec-ril-smsc-shim: real RIL function table has null onRequest");
        return real;
    }

    static RIL_RadioFunctions sShimFunctions;
    sShimFunctions = *real;

    gReal_onRequest = real->onRequest;
    sShimFunctions.onRequest = Shim_onRequest;

    ALOGI("sec-ril-smsc-shim: installed SMSC and data-call MTU normalization for %s", REAL_LIB_NAME);
    return &sShimFunctions;
}
