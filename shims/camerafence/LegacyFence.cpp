/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

#include <android-base/unique_fd.h>
#include <sync/sync.h>

#include <cerrno>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace samsung {

// The camera blob allocates and reference-counts this pre-virtual Fence layout
// itself. Its inlined destructor closes the unique_fd at offset 4.
struct Fence {
    explicit Fence(int fd);
    int wait(int timeout);

    std::atomic<int32_t> strongCount{0};
    android::base::unique_fd fenceFd;
};

static_assert(std::is_standard_layout_v<Fence>);
static_assert(sizeof(Fence) == 8);
static_assert(offsetof(Fence, strongCount) == 0);
static_assert(offsetof(Fence, fenceFd) == 4);

Fence::Fence(int fd) : fenceFd(fd) {}

int Fence::wait(int timeout) {
    if (fenceFd.get() == -1) {
        return 0;
    }
    return sync_wait(fenceFd.get(), timeout) < 0 ? -errno : 0;
}

}  // namespace samsung
