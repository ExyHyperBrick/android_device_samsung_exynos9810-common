# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
"""Guarded separate camera-50 controls for the verified G960F stock app layout."""
import re

HELPER = "Lorg/lineageos/camera/compat/TelephotoCompat;"
SETTINGS = "Lcom/sec/android/app/camera/setting/CameraSettingsImpl;"
CAMERA = "Lcom/sec/android/app/camera/interfaces/CameraSettings;"
GROUP = "Lcom/sec/android/app/camera/menu/ZoomChangeGroup;"
CONTEXT = "Lcom/sec/android/app/camera/interfaces/CameraContext;"
COMMAND = "Lcom/sec/android/app/camera/interfaces/CommandId;"


def _once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"Unexpected telephoto stock sequence: {before[:100]}")
    return text.replace(before, after)


def _edit(path, signature, edit):
    text = path.read_text()
    pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                         + r"\n.*?^\.end method$", re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"Expected one telephoto method: {path}: {signature}")
    match = matches[0]
    path.write_text(text[:match.start()] + edit(match[0]) + text[match.end():])


def _entry(body, instructions):
    return re.sub(r"(    \.locals \d+\n)", r"\1" + instructions + "\n", body, count=1)


def _wrap(path, signature, renamed, wrapper):
    _edit(path, signature, lambda body: _once(body, ".method " + signature,
                                             ".method private " + renamed))
    with path.open("a") as stream:
        stream.write("\n" + wrapper + "\n")


def patch_telephoto(decoded):
    # Resolve metadata before Feature's static initializer consumes the loaded XML map.
    loader = decoded / "smali/com/samsung/android/camera/feature/FeatureLoader.smali"
    feature_init = f"""
    sget-object v0, Lcom/samsung/android/camera/feature/FeatureLoader;->mContext:Landroid/content/Context;
    sget-object v1, Lcom/samsung/android/camera/feature/FeatureLoader;->mFeatureList:Ljava/util/HashMap;
    invoke-static {{v0, v1}}, {HELPER}->applyFeatures(Landroid/content/Context;Ljava/util/Map;)V
"""
    _edit(loader, "public static loadFeature(Landroid/content/Context;)V",
          lambda body: body.replace("    return-void", feature_init + "    return-void"))

    for suffix in ("1", "11"):
        path = decoded / ("smali_classes2/com/sec/android/app/camera/util/"
                          f"ShootingModeMap$2${suffix}.smali")
        owner = f"Lcom/sec/android/app/camera/util/ShootingModeMap$2${suffix};"
        added = f"""
    sget-boolean p1, Lcom/samsung/android/camera/feature/Feature;->SUPPORT_BACK_TELE_CAMERA:Z
    if-eqz p1, :compat_tele_done
    const/4 v0, 0x2
    const/16 p1, 0x64
    invoke-static {{p1}}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object p1
    invoke-virtual {{p0, v0, p1}}, {owner}->put(ILjava/lang/Object;)V
    :compat_tele_done
"""
        path.write_text(_once(path.read_text(), "    return-void", added + "    return-void"))

    settings = decoded / "smali_classes2/com/sec/android/app/camera/setting/CameraSettingsImpl.smali"
    # The custom-mode setting is an override context, not the active mode.
    # Export the actual field used by setShootingMode and its notifications.
    camera_interface = decoded / "smali_classes2/com/sec/android/app/camera/interfaces/CameraSettings.smali"
    interface_text = camera_interface.read_text()
    if "compatShootingMode" in interface_text:
        raise ValueError("Current-mode compatibility getter already installed")
    camera_interface.write_text(interface_text + "\n.method public abstract compatShootingMode()I\n.end method\n")
    with settings.open("a") as stream:
        stream.write(f"""
.method public compatShootingMode()I
    .locals 0
    iget p0, p0, {SETTINGS}->mShootingMode:I
    return p0
.end method
""")

    # The stock app calls rear-facing1 and front-facing0. Separate sensors
    # do not satisfy Photo/Video's Samsung seamless or ultra-wide zoom gate.
    # Check their validated rear capability first; preserve the stock fallback.
    menu = decoded / "smali_classes2/com/sec/android/app/camera/menu/AbstractBaseMenu.smali"
    _edit(menu, "private isZoomChangeButtonAvailable()Z", lambda body: _entry(body, f"""
    iget-object v0, p0, Lcom/sec/android/app/camera/menu/AbstractBaseMenu;->mCameraContext:{CONTEXT}
    invoke-interface {{v0}}, {CONTEXT}->getCameraSettings(){CAMERA}
    move-result-object v0
    invoke-interface {{v0}}, {CAMERA}->getCameraFacing()I
    move-result v0
    iget-object v1, p0, Lcom/sec/android/app/camera/menu/AbstractBaseMenu;->mCameraContext:{CONTEXT}
    invoke-interface {{v1}}, {CONTEXT}->getCameraSettings(){CAMERA}
    move-result-object v1
    invoke-interface {{v1}}, {CAMERA}->compatShootingMode()I
    move-result v1
    invoke-static {{v0, v1}}, {HELPER}->isLensButtonAvailable(II)Z
    move-result v0
    if-eqz v0, :compat_stock_zoom_buttons
    return v0
    :compat_stock_zoom_buttons
"""))

    # Normalize only the persisted startup ID. Keep the currently opened ID intact
    # during a mode transition so CLOSE_CAMERA always closes the actual old device.
    _edit(settings, "public getCameraId()I", lambda body: _once(body,
        f"    invoke-direct {{p0, v1, v0}}, {SETTINGS}->loadPreferences(Ljava/lang/String;I)I\n\n    move-result p0\n\n    return p0",
        f"""    invoke-direct {{p0, v1, v0}}, {SETTINGS}->loadPreferences(Ljava/lang/String;I)I
    move-result v0
    invoke-virtual {{p0}}, {SETTINGS}->compatShootingMode()I
    move-result v1
    invoke-static {{v0, v1}}, {HELPER}->normalizeCameraId(II)I
    move-result p0
    return p0"""))
    _wrap(settings, "public getBackCameraLensType()I", "compatBackCameraLensType()I", f"""
.method public getBackCameraLensType()I
    .locals 2
    invoke-direct {{p0}}, {SETTINGS}->compatBackCameraLensType()I
    move-result v0
    invoke-virtual {{p0}}, {SETTINGS}->compatShootingMode()I
    move-result v1
    invoke-static {{v0, v1}}, {HELPER}->normalizeLensType(II)I
    move-result v0
    return v0
.end method""")
    _wrap(settings, "public getBackCamcorderResolution()I", "compatBackCamcorderResolution()I", f"""
.method public getBackCamcorderResolution()I
    .locals 2
    invoke-direct {{p0}}, {SETTINGS}->compatBackCamcorderResolution()I
    move-result v0
    invoke-virtual {{p0}}, {SETTINGS}->getCameraId()I
    move-result v1
    invoke-static {{v1, v0}}, {HELPER}->constrainVideoResolution(II)I
    move-result v0
    return v0
.end method""")
    _edit(settings, "public setBackCamcorderResolution(I)V", lambda body: _entry(body, f"""
    invoke-virtual {{p0}}, {SETTINGS}->getCameraId()I
    move-result v0
    const/16 v1, 0x64
    if-ne v0, v1, :compat_tele_video_set_original
    invoke-static {{p1}}, {HELPER}->selectVideoResolution(I)I
    move-result p1
    iget-object v0, p0, {SETTINGS}->mSettingKeyMap:Ljava/util/Map;
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->BACK_CAMCORDER_RESOLUTION:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    invoke-interface {{v0, v1}}, Ljava/util/Map;->get(Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Lcom/sec/android/app/camera/setting/SettingValue;
    invoke-virtual {{v0, p1}}, Lcom/sec/android/app/camera/setting/SettingValue;->notifyCameraSettingChanged(I)V
    return-void
    :compat_tele_video_set_original
"""))
    # Explicit target resolution is queried before the old sensor is closed.
    _edit(settings, "public getCamcorderResolution(I)I", lambda body: _once(body,
        f"invoke-virtual {{p0}}, {SETTINGS}->getBackCamcorderResolution()I",
        f"invoke-direct {{p0}}, {SETTINGS}->compatBackCamcorderResolution()I"))
    _wrap(settings, "public getCamcorderResolution(I)I", "compatCamcorderResolution(I)I", f"""
.method public getCamcorderResolution(I)I
    .locals 1
    invoke-direct {{p0, p1}}, {SETTINGS}->compatCamcorderResolution(I)I
    move-result v0
    invoke-static {{p1, v0}}, {HELPER}->constrainVideoResolution(II)I
    move-result v0
    return v0
.end method""")
    # This callback occurs after blocking CLOSE_CAMERA, before target OPEN_CAMERA.
    _edit(settings, "public setCameraId(I)V", lambda body: _entry(body, f"""
    if-ltz p1, :compat_tele_set_done
    invoke-virtual {{p0}}, {SETTINGS}->getCameraId()I
    move-result v0
    const/16 v1, 0x64
    if-eq p1, v1, :compat_tele_reset
    if-ne v0, v1, :compat_tele_set_done
    :compat_tele_reset
    const/16 v0, 0x3e8
    invoke-virtual {{p0, v0}}, {SETTINGS}->setZoomValue(I)V
    const/4 v0, 0x0
    if-ne p1, v1, :compat_tele_lens
    const/4 v0, 0x2
    :compat_tele_lens
    invoke-virtual {{p0, v0}}, {SETTINGS}->setBackCameraLensType(I)V
    :compat_tele_set_done
"""))

    group = decoded / "smali_classes2/com/sec/android/app/camera/menu/ZoomChangeGroup.smali"
    _edit(group, "private isSupportBackTeleCamera()Z", lambda body: _entry(
            _once(body, "    .locals 1", "    .locals 2"), f"""
    iget-object v0, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v0}}, {CAMERA}->getCameraFacing()I
    move-result v0
    iget-object v1, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v1}}, {CAMERA}->compatShootingMode()I
    move-result v1
    invoke-static {{v0, v1}}, {HELPER}->isAvailableForFacing(II)Z
    move-result v0
    if-nez v0, :compat_tele_supported
    const/4 v0, 0x0
    return v0
    :compat_tele_supported
"""))
    # Separate sensors use their own relative 1x range, not seamless zoom thresholds.
    _edit(group, "private initZoomLevel()V", lambda body: _entry(body, f"""
    iget-boolean v0, p0, {GROUP}->mIsSupportBackTeleCamera:Z
    if-eqz v0, :compat_tele_level_done
    const/16 v0, 0x7d0
    iput v0, p0, {GROUP}->mTeleZoomLevel:I
    :compat_tele_level_done
"""))
    _edit(group, "private getZoomType(I)I", lambda body: _entry(body, f"""
    iget-object v0, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v0}}, {CAMERA}->getCameraFacing()I
    move-result v0
    iget-object v1, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v1}}, {CAMERA}->compatShootingMode()I
    move-result v1
    invoke-static {{v0, v1}}, {HELPER}->isAvailableForFacing(II)Z
    move-result v0
    if-eqz v0, :compat_tele_zoom_original
    iget-object v0, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v0}}, {CAMERA}->getCameraId()I
    move-result v0
    const/16 v1, 0x64
    const/4 v2, 0x0
    if-ne v0, v1, :compat_tele_zoom_type
    const/4 v2, 0x2
    :compat_tele_zoom_type
    return v2
    :compat_tele_zoom_original
"""))
    _edit(group, "private setZoomText(I)V", lambda body: _entry(body, f"""
    iget-object v0, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v0}}, {CAMERA}->getCameraId()I
    move-result v0
    invoke-static {{p1, v0}}, {HELPER}->displayZoom(II)I
    move-result p1
"""))
    _edit(group, "public onClick(Lcom/samsung/android/glview/GLView;)Z", lambda body: _once(body,
        "    :cond_2\n    const/4 v0, 0x0", f"""    :cond_2
    iget-object v0, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v0}}, {CAMERA}->getCameraFacing()I
    move-result v0
    iget-object v2, p0, {GROUP}->mCameraSettings:{CAMERA}
    invoke-interface {{v2}}, {CAMERA}->compatShootingMode()I
    move-result v2
    invoke-static {{v0, v2}}, {HELPER}->isAvailableForFacing(II)Z
    move-result v0
    if-eqz v0, :compat_tele_click_original
    iget v0, p0, {GROUP}->mType:I
    const/4 v2, 0x4
    if-ne v0, v2, :compat_tele_click_original
    invoke-virtual {{p1}}, Lcom/samsung/android/glview/GLView;->getTag()I
    move-result v0
    if-eqz v0, :compat_tele_normal_button
    const/4 v2, 0x2
    if-ne v0, v2, :compat_tele_click_original
    sget-object v2, {COMMAND}->BACK_CAMERA_ZOOM_TELE:{COMMAND}
    goto :compat_tele_button
    :compat_tele_normal_button
    sget-object v2, {COMMAND}->BACK_CAMERA_ZOOM_NORMAL:{COMMAND}
    :compat_tele_button
    iget-object v0, p0, {GROUP}->mCameraContext:{CONTEXT}
    invoke-interface {{v0}}, {CONTEXT}->getCommandReceiver()Lcom/sec/android/app/camera/interfaces/CommandInterface;
    move-result-object v0
    invoke-interface {{v0, v2}}, Lcom/sec/android/app/camera/interfaces/CommandInterface;->onLensTypeSelectCommand({COMMAND})Z
    move-result v0
    return v0
    :compat_tele_click_original
    const/4 v0, 0x0"""))

    receiver = decoded / "smali/com/sec/android/app/camera/CommandReceiver.smali"
    _edit(receiver, f"public onLensTypeSelectCommand({COMMAND})Z", lambda body: _entry(body, f"""
    iget-object v0, p0, Lcom/sec/android/app/camera/CommandReceiver;->mCameraSettings:{CAMERA}
    invoke-interface {{v0}}, {CAMERA}->getCameraFacing()I
    move-result v0
    iget-object v1, p0, Lcom/sec/android/app/camera/CommandReceiver;->mCameraSettings:{CAMERA}
    invoke-interface {{v1}}, {CAMERA}->compatShootingMode()I
    move-result v1
    invoke-static {{v0, v1}}, {HELPER}->isAvailableForFacing(II)Z
    move-result v0
    if-eqz v0, :compat_tele_record_done
    sget-object v0, {COMMAND}->BACK_CAMERA_ZOOM_TELE:{COMMAND}
    if-eq p1, v0, :compat_tele_record_check
    sget-object v0, {COMMAND}->BACK_CAMERA_ZOOM_NORMAL:{COMMAND}
    if-ne p1, v0, :compat_tele_record_done
    :compat_tele_record_check
    iget-object v0, p0, Lcom/sec/android/app/camera/CommandReceiver;->mCameraContext:Lcom/sec/android/app/camera/Camera;
    invoke-virtual {{v0}}, Lcom/sec/android/app/camera/Camera;->isRecording()Z
    move-result v0
    if-eqz v0, :compat_tele_record_done
    const/4 v0, 0x0
    return v0
    :compat_tele_record_done
"""))

    # Filter only copies in the two rear ordinary-video selection UIs.
    for name in ("ResolutionListActivity", "PreferenceSettingFragment"):
        path = decoded / (f"smali_classes2/com/sec/android/app/camera/setting/{name}.smali")
        owner = f"Lcom/sec/android/app/camera/setting/{name};"
        before = "    invoke-static {}, Lcom/sec/android/app/camera/util/CameraResolution;->getSelectableBackVideoResolutionList()[Lcom/sec/android/app/camera/interfaces/Resolution;\n\n    move-result-object "
        text = path.read_text()
        pattern = re.escape(before) + r"(v\d+|p\d+)"
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            raise ValueError(f"Expected one rear video UI list: {name}")
        match = matches[0]
        result = match[1]
        # Preserve the receiver before stock switch code reuses p0 as an integer.
        method_start = text.rfind("\n.method ", 0, match.start()) + 1
        method_end = text.index("\n.end method", match.end()) + len("\n.end method")
        body = text[method_start:method_end]
        locals_match = re.search(r"    \.locals (\d+)", body)
        scratch = "v" + locals_match[1]
        updated = body.replace(locals_match[0],
                "    .locals " + str(int(locals_match[1]) + 1), 1)
        updated = _entry(updated, "    move-object " + scratch + ", p0")
        replacement = f"""    iget-object {scratch}, {scratch}, {owner}->mCameraSettings:{SETTINGS}
    invoke-virtual {{{scratch}}}, {SETTINGS}->getCameraId()I
    move-result {scratch}
""" + match[0] + f"""
    invoke-static {{{result}, {scratch}}}, {HELPER}->filterVideoResolutions([Ljava/lang/Object;I)[Ljava/lang/Object;
    move-result-object {result}
    check-cast {result}, [Lcom/sec/android/app/camera/interfaces/Resolution;"""
        updated = _once(updated, match[0], replacement)
        path.write_text(text[:method_start] + updated + text[method_end:])
