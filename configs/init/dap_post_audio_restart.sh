#!/system/bin/sh

TAG="dap_post_audio_restart"
PKG="org.lineageos.dap"
RCV="org.lineageos.dap/.BootCompletedReceiver"

log -p i -t "$TAG" "waiting for audioserver restart to settle"
sleep 12

if ! cmd package path "$PKG" >/dev/null 2>&1; then
    log -p i -t "$TAG" "$PKG not installed; skipping"
    exit 0
fi

log -p i -t "$TAG" "re-sending SamsungDAP locked boot receiver"

OUT="$(am broadcast --user 0 \
    -f 0x20 \
    -n "$RCV" \
    -a android.intent.action.LOCKED_BOOT_COMPLETED 2>&1)"
RC=$?

log -p i -t "$TAG" "broadcast rc=$RC output=$OUT"
log -p i -t "$TAG" "done"
exit 0
