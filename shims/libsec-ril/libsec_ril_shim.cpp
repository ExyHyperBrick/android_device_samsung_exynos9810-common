// SPDX-License-Identifier: Apache-2.0
//
// Summary:
// - Wraps Samsung vendor libsec-ril*.so and synthesizes EF_SPN (0x6F46) when the
//   modem returns an "empty" SPN (typical payload 0x00 + 0xFF...).
// - This restores status-bar SPN display on recent Android releases without
//   per-carrier overrides.
//
// Based on:
// - AOSP RIL C-API and SIM I/O definitions:
//   https://android.googlesource.com/platform/hardware/ril/+/refs/heads/master/include/telephony/ril.h
// - Telephony SPN/PLMN display logic:
//   https://android.googlesource.com/platform/frameworks/opt/telephony/+/refs/heads/master/src/java/com/android/internal/telephony/ServiceStateTracker.java
//   https://android.googlesource.com/platform/frameworks/opt/telephony/+/refs/heads/master/src/java/com/android/internal/telephony/uicc/IccRecords.java
// - EF_SPN layout (3GPP TS 31.102, EF 6F46).
//
// Build/packaging notes:
// - This file expects -DRIL_SHLIB and -DREAL_LIB_NAME to be set in Android.bp.
// - Install the original Samsung blobs as libsec-ril[-dsds]-impl.so and ship
//   this shim under the canonical names so rild loads it first.
// - Link against libbase, liblog, libdl, and include ril.h via header_lib or
//   hardware/ril/include.
//
// Runtime properties (vendor namespace):
//   persist.vendor.ril.shim_log        = 1 to enable logs (default: 0)
//   persist.vendor.ril.shim_spn_force  = 1 to always synthesize EF_SPN
//   persist.vendor.ril.shim_spn_value  = explicit SPN override for testing
//
// NOTE: This shim only alters EF_SPN READ_BINARY responses. All other requests
//       and unsolicited responses are forwarded unchanged.

#include <dlfcn.h>
#include <log/log.h>
#include <pthread.h>
#include <stddef.h>   // offsetof
#include <stdlib.h>   // strdup
#include <string.h>

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include <android-base/properties.h>
#include <android-base/strings.h>
#include <telephony/ril.h>

#ifndef REAL_LIB_NAME
#error "REAL_LIB_NAME must be defined by the build (e.g., libsec-ril-impl.so)"
#endif

static const char* kRealPath = "/vendor/lib64/" REAL_LIB_NAME;

// ----- logging (quiet by default; enable via persist.vendor.ril.shim_log=1)
static bool gLog = false;
#define SHIM_LOGI(...) do { if (gLog) ALOGI(__VA_ARGS__); } while (0)
#define SHIM_LOGW(...) do { if (gLog) ALOGW(__VA_ARGS__); } while (0)

// ----- real vendor RIL pointers
static void* gRealHandle = nullptr;
static const RIL_RadioFunctions* (*gReal_RIL_Init)(const RIL_Env*, int, char**) = nullptr;
static const RIL_RadioFunctions* gRealFuncs = nullptr;

static RIL_Env gEnvOrig;  // framework callbacks
static RIL_Env gEnvShim;  // wrapped callbacks
static void (*gReal_onRequest)(int, void*, size_t, RIL_Token) = nullptr;

// ----- SIM_IO metadata (to match completions)
struct SimIoMeta { int command = 0; int fileid = 0; int p3 = 0; };
static pthread_mutex_t gMapLock = PTHREAD_MUTEX_INITIALIZER;
static std::unordered_map<RIL_Token, SimIoMeta> gSimIoMeta;

// ----- instance/slot (DSDS-aware)
static int gInstanceId = 0;
static void ParseInstanceId(int argc, char** argv) {
    for (int i = 0; i < argc; ++i) {
        const char* a = argv[i]; if (!a) continue;
        if (const char* p = strstr(a, "clientId=")) { gInstanceId = atoi(p + 9); continue; }
        if ((strcmp(a, "-c") == 0 || strcmp(a, "--slot") == 0 || strcmp(a, "--instance") == 0) && i + 1 < argc) {
            gInstanceId = atoi(argv[++i]); continue;
        }
    }
    if (gInstanceId < 0 || gInstanceId > 1) gInstanceId = 0;
}

static std::string pickTokenForInstance(const std::string& csv, int inst) {
    auto v = android::base::Split(csv, ",");
    if (!v.empty() && inst >= 0 && inst < (int)v.size()) {
        auto s = android::base::Trim(v[inst]);
        if (!s.empty() && s != "unknown") return s;
    }
    for (auto& t : v) {
        auto s = android::base::Trim(t);
        if (!s.empty() && s != "unknown") return s;
    }
    return "";
}

static std::string readSpnForInstance(int inst) {
    // explicit override (testing)
    std::string spn = android::base::GetProperty("persist.vendor.ril.shim_spn_value", "");
    if (!spn.empty()) return spn;

    // SIM operator alpha (comma-separated across slots)
    spn = pickTokenForInstance(android::base::GetProperty("gsm.sim.operator.alpha", ""), inst);
    if (!spn.empty()) return spn;

    // PLMN alpha as last resort
    return pickTokenForInstance(android::base::GetProperty("gsm.operator.alpha", ""), inst);
}

static std::string bytes_to_hex(const std::vector<uint8_t>& v) {
    static const char* hexd = "0123456789ABCDEF";
    std::string out; out.reserve(v.size() * 2);
    for (uint8_t b : v) { out.push_back(hexd[(b >> 4) & 0xF]); out.push_back(hexd[b & 0xF]); }
    return out;
}

// EF_SPN builder: byte0=display(0x00=show), bytes[1..]=ASCII name, rest=0xFF
static std::string build_spn_simio_hex(const std::string& spn, int p3) {
    if (p3 < 2 || p3 > 64) p3 = 17;
    std::vector<uint8_t> buf(p3, 0xFF);
    buf[0] = 0x00;
    const size_t max = (p3 > 1) ? (size_t)(p3 - 1) : 0;
    for (size_t i = 0; i < spn.size() && i < max; ++i) buf[1 + i] = (uint8_t)spn[i];
    return bytes_to_hex(buf);
}

// EF_SPN considered "empty" if len<2, all 0x00, or bytes[1..] all 0xFF (covers 0x00/0x02 + FF..)
static bool simio_hex_spn_is_empty(const char* hex) {
    if (!hex || !*hex) return true;
    std::vector<uint8_t> b; b.reserve(strlen(hex) / 2);
    int hi = -1;
    for (const char* p = hex; *p; ++p) {
        char c = *p; if (c == ' ' || c == '\t' || c == '\n' || c == '\r') continue;
        int v = (c >= '0' && c <= '9') ? c - '0' :
                (c >= 'a' && c <= 'f') ? c - 'a' + 10 :
                (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
        if (v < 0) return false; // non-hex: treat as not-empty to avoid masking issues
        if (hi < 0) hi = v; else { b.push_back((uint8_t)((hi << 4) | v)); hi = -1; }
    }
    if (b.size() < 2) return true;
    bool all0 = true, tailFF = true;
    for (auto x : b) if (x != 0x00) { all0 = false; break; }
    for (size_t i = 1; i < b.size(); ++i) if (b[i] != 0xFF) { tailFF = false; break; }
    return all0 || tailFF;
}

// Poll for SPN prop then trigger a EF_SPN re-read (guarded to avoid repeats)
struct SpnPollCtx { int tries; };
static bool gPollScheduled = false;
static void SpnPollCb(void* param);

static void scheduleSpnPoll(int tries) {
    if (gPollScheduled) return;
    gPollScheduled = true;
    auto* ctx = new SpnPollCtx{tries};
    timeval tv{.tv_sec = 1, .tv_usec = 0};
    gEnvOrig.RequestTimedCallback(SpnPollCb, ctx, &tv);
}

static void triggerSpnRefresh() {
    // Adjust struct name/fields if your ril.h uses a different version.
    RIL_SimRefreshResponse_v7 r{};
    r.result = SIM_FILE_UPDATE;
    r.ef_id  = 0x6F46;  // EF_SPN
    r.aid    = nullptr;
    gEnvOrig.OnUnsolicitedResponse(RIL_UNSOL_SIM_REFRESH, &r, sizeof(r));
}

static void SpnPollCb(void* param) {
    std::unique_ptr<SpnPollCtx> ctx((SpnPollCtx*)param);
    std::string spn = readSpnForInstance(gInstanceId);
    if (!spn.empty()) {
        SHIM_LOGI("sec-ril-shim: SPN available -> SIM_REFRESH(EF_SPN)");
        triggerSpnRefresh();
        gPollScheduled = false;
        return;
    }
    if (--ctx->tries > 0) {
        timeval tv{.tv_sec = 1, .tv_usec = 0};
        gEnvOrig.RequestTimedCallback(SpnPollCb, ctx.release(), &tv);
    } else {
        SHIM_LOGW("sec-ril-shim: SPN still empty after retries");
        gPollScheduled = false;
    }
}

// ----- wrapped env callbacks -----
static void Shim_OnRequestComplete(RIL_Token t, RIL_Errno e, void* resp, size_t resplen) {
    // pop SIM_IO meta (if present)
    pthread_mutex_lock(&gMapLock);
    auto it = gSimIoMeta.find(t);
    SimIoMeta meta = (it != gSimIoMeta.end()) ? it->second : SimIoMeta{};
    if (it != gSimIoMeta.end()) gSimIoMeta.erase(it);
    pthread_mutex_unlock(&gMapLock);

    bool handled = false;

    // Intercept EF_SPN READ_BINARY (0x6F46 / 0xB0)
    if (meta.fileid == 0x6F46 && meta.command == 0xB0) {
        const RIL_SIM_IO_Response* io = (const RIL_SIM_IO_Response*)resp;
        const size_t hexlen = (io && io->simResponse) ? strlen(io->simResponse) : 0;

        const bool empty = (e != RIL_E_SUCCESS) || (io == nullptr) ||
                           (io->sw1 != 0x90) || (io->sw2 != 0x00) ||
                           simio_hex_spn_is_empty(io ? io->simResponse : nullptr);

        const bool force = android::base::GetBoolProperty("persist.vendor.ril.shim_spn_force", false);
        std::string spn = readSpnForInstance(gInstanceId);

        if (gLog) {
            SHIM_LOGI("sec-ril-shim(%s): inst=%d EF_SPN sw=%02X/%02X len=%zu empty=%d force=%d spn=\"%s\"",
                      REAL_LIB_NAME, gInstanceId, io ? io->sw1 : -1, io ? io->sw2 : -1,
                      hexlen, (int)empty, (int)force, spn.c_str());
        }

        if (force || (empty && !spn.empty())) {
            const int p3 = meta.p3 > 0 ? meta.p3 : 17;
            std::string simHex = build_spn_simio_hex(spn, p3);

            RIL_SIM_IO_Response fake{};
            fake.sw1 = 0x90; fake.sw2 = 0x00;
            fake.simResponse = ::strdup(simHex.c_str());  // ownership transferred to libril

            SHIM_LOGI("sec-ril-shim(%s): inst=%d %s EF_SPN -> \"%s\" (p3=%d, orig=%zu)",
                      REAL_LIB_NAME, gInstanceId, force ? "FORCE" : "synth", spn.c_str(), p3, hexlen);

            gEnvOrig.OnRequestComplete(t, RIL_E_SUCCESS, (void*)&fake, sizeof(fake));
            handled = true;
        } else if (empty && spn.empty()) {
            // SPN not available yet → schedule a short poll and refresh when it appears
            scheduleSpnPoll(/*tries=*/8); // ~8s worst-case
        } else {
            // Non-empty EF_SPN from modem → pass through unchanged
        }
    }

    if (!handled) gEnvOrig.OnRequestComplete(t, e, resp, resplen);
}

static void Shim_OnUnsolicitedResponse(int unsol, const void* data, size_t len) {
    gEnvOrig.OnUnsolicitedResponse(unsol, data, len);
}

static void Shim_RequestTimedCallback(RIL_TimedCallback cb, void* param, const timeval* tv) {
    gEnvOrig.RequestTimedCallback(cb, param, tv);
}

// ----- track SIM_IO requests (tolerate v5/v6 struct sizes)
static void Shim_onRequest(int req, void* data, size_t len, RIL_Token t) {
    if (req == RIL_REQUEST_SIM_IO && data &&
        len >= (int)offsetof(RIL_SIM_IO_v6, data)) {
        const RIL_SIM_IO_v6* in = (const RIL_SIM_IO_v6*)data; // leading fields compatible across versions
        SimIoMeta m; m.command = in->command; m.fileid = in->fileid; m.p3 = in->p3;
        pthread_mutex_lock(&gMapLock); gSimIoMeta[t] = m; pthread_mutex_unlock(&gMapLock);
        SHIM_LOGI("sec-ril-shim: SIM_IO req=0x%X file=0x%X p3=%d", in->command, in->fileid, in->p3);
    }
    gReal_onRequest(req, data, len, t);
}

// ----- entry point -----
extern "C"
const RIL_RadioFunctions* RIL_Init(const RIL_Env* env, int argc, char** argv) {
    gLog = android::base::GetBoolProperty("persist.vendor.ril.shim_log", false);
    ParseInstanceId(argc, argv);

    gEnvOrig = *env;
    gEnvShim = *env;
    gEnvShim.OnRequestComplete     = Shim_OnRequestComplete;
    gEnvShim.OnUnsolicitedResponse = Shim_OnUnsolicitedResponse;
    gEnvShim.RequestTimedCallback  = Shim_RequestTimedCallback;

    gRealHandle = dlopen(kRealPath, RTLD_NOW);
    if (!gRealHandle) { ALOGE("sec-ril-shim: dlopen(%s) failed: %s", kRealPath, dlerror()); return nullptr; }
    gReal_RIL_Init = (decltype(gReal_RIL_Init))dlsym(gRealHandle, "RIL_Init");
    if (!gReal_RIL_Init) { ALOGE("sec-ril-shim: dlsym(RIL_Init) failed: %s", dlerror()); return nullptr; }

    const RIL_RadioFunctions* real = gReal_RIL_Init(&gEnvShim, argc, argv);
    if (!real) { ALOGE("sec-ril-shim: real RIL_Init returned null"); return nullptr; }

    static RIL_RadioFunctions sFns;
    sFns = *real;
    gRealFuncs     = real;
    gReal_onRequest = real->onRequest;
    sFns.onRequest  = Shim_onRequest;

    SHIM_LOGI("sec-ril-shim: init ok (using %s), instance=%d", kRealPath, gInstanceId);
    return &sFns;
}
