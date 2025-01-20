#include <stdint.h>
#include <system/graphics.h>
#include <ui/GraphicBufferMapper.h>
#include <ui/Rect.h>
#include <utils/Errors.h>

using android::GraphicBufferMapper;
using android::Rect;
using android::status_t;

// Use global namespace for buffer_handle_t
using ::buffer_handle_t;

extern "C" {
status_t
_ZN7android19GraphicBufferMapper9lockAsyncEPK13native_handlemmRKNS_4RectEPPviPiS9_(
    void *thisptr, buffer_handle_t handle, unsigned long producerUsage,
    unsigned long consumerUsage, const Rect &bounds, void **vaddr, int fenceFd,
    [[maybe_unused]] int32_t *outBytesPerPixel,
    [[maybe_unused]] int32_t *outBytesPerStride) {

  // Cast 'thisptr' to a GraphicBufferMapper instance
  auto *gpm = static_cast<GraphicBufferMapper *>(thisptr);

  // Forward the call to the real lockAsync method
  return gpm->lockAsync(handle, static_cast<uint64_t>(producerUsage),
                        static_cast<uint64_t>(consumerUsage), bounds, vaddr,
                        fenceFd);
}
}