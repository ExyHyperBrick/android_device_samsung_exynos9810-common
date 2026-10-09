#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Transform the G960F camera into the app-local LineageOS camera port.

The compatibility Java code is compiled and appended by Soong separately.
Stock imaging/SEF DEX remains part of this transformed base APK.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from telephoto_patch import patch_telephoto

ANDROID = "{http://schemas.android.com/apk/res/android}"
ET.register_namespace("android", ANDROID[1:-1])
HERE = Path(__file__).resolve().parent
MARKER = "assets/lineage_samsung_camera.json"


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


SPR_DRAWABLE_LOADER = r'''
# Samsung SPR is not an AOSP bitmap format. Read only the magic, close this
# stream, then let the stock SPR renderer reopen it with its density handling.
.method private static loadCompatibleDrawable(Landroid/content/res/Resources;ILandroid/content/res/Resources$Theme;)Landroid/graphics/drawable/Drawable;
    .locals 4
    const/4 v0, 0x0
    :try_start_header
    invoke-virtual {p0, p1}, Landroid/content/res/Resources;->openRawResource(I)Ljava/io/InputStream;
    move-result-object v1
    new-instance v2, Ljava/io/DataInputStream;
    invoke-direct {v2, v1}, Ljava/io/DataInputStream;-><init>(Ljava/io/InputStream;)V
    move-object v0, v2
    invoke-virtual {v0}, Ljava/io/DataInputStream;->readInt()I
    move-result v1
    invoke-virtual {v0}, Ljava/io/DataInputStream;->close()V
    :try_end_header
    .catch Ljava/io/IOException; {:try_start_header .. :try_end_header} :catch_header
    .catch Landroid/content/res/Resources$NotFoundException; {:try_start_header .. :try_end_header} :catch_header
    const v2, 0x53505200
    if-eq v1, v2, :spr_resource
    const v2, 0x53564600
    if-eq v1, v2, :spr_resource
    :ordinary_resource
    invoke-virtual {p0, p1, p2}, Landroid/content/res/Resources;->getDrawable(ILandroid/content/res/Resources$Theme;)Landroid/graphics/drawable/Drawable;
    move-result-object v0
    return-object v0
    :spr_resource
    invoke-static {p0, p1}, Lcom/samsung/android/graphics/spr/SemPathRenderingDrawable;->createFromResourceStream(Landroid/content/res/Resources;I)Lcom/samsung/android/graphics/spr/SemPathRenderingDrawable;
    move-result-object v0
    return-object v0
    :catch_header
    move-exception v3
    if-eqz v0, :ordinary_resource
    :try_start_close
    invoke-virtual {v0}, Ljava/io/DataInputStream;->close()V
    :try_end_close
    .catch Ljava/io/IOException; {:try_start_close .. :try_end_close} :catch_close
    goto :ordinary_resource
    :catch_close
    move-exception v3
    goto :ordinary_resource
.end method
'''


def patch_gl_spr_loader(decoded):
    path = Path(decoded) / "smali/com/samsung/android/glview/GLResourceTexture.smali"
    body = path.read_text()
    before = "invoke-virtual {v0, v2, v1}, Landroid/content/res/Resources;->getDrawable(ILandroid/content/res/Resources$Theme;)Landroid/graphics/drawable/Drawable;"
    after = "invoke-static {v0, v2, v1}, Lcom/samsung/android/glview/GLResourceTexture;->loadCompatibleDrawable(Landroid/content/res/Resources;ILandroid/content/res/Resources$Theme;)Landroid/graphics/drawable/Drawable;"
    if body.count(before) != 1 or "loadCompatibleDrawable(" in body:
        raise ValueError("Unexpected stock GL resource drawable lookup")
    path.write_text(body.replace(before, after) + "\n" + SPR_DRAWABLE_LOADER)



def patch_runtime_methods(decoded):
    """Adapt services, typed keys, output constructors and stream roles."""
    def patch_method(relative, signature, replacement):
        path = decoded / relative
        text = path.read_text()
        pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                             + r"\n.*?^\.end method$", re.DOTALL)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError(f"Expected one stock method: {relative}: {signature}")
        match = matches[0]
        body = replacement(match[0])
        path.write_text(text[:match.start()] + body + text[match.end():])

    def guard_mdnie(body):
        cast = "    check-cast p0, Lcom/samsung/android/hardware/display/SemMdnieManager;"
        if body.count(cast) != 1 or "    :cond_1\n    return-void" not in body:
            raise ValueError("Unexpected stock mDNIe service lookup")
        return body.replace(cast, cast + "\n\n    if-eqz p0, :cond_1")

    patch_method(
        "smali_classes2/com/sec/android/app/camera/util/Util.smali",
        "public static enableMdnieCameraMode(Landroid/content/Context;Z)V",
        guard_mdnie)

    def fallback_output(body, field, parameters, arguments):
        lookup = ("    sget-object v1, Lcom/samsung/android/camera/core2/device/"
                  + "CamDeviceImpl;->" + field + ":Ljava/lang/reflect/Constructor;")
        if body.count(lookup) != 1 or body.count("    :try_end_0") != 1:
            raise ValueError(f"Unexpected stock output constructor: {field}")
        # The stock extra argument is Samsung's mOption. The remaining
        # arguments are group=-1/rotation=0 or deferred Size/Class, matching
        # these public constructors. Keep the stock path when it exists.
        fallback = (lookup + "\n\n"
                    "    if-nez v1, :lineage_stock_output_constructor\n\n"
                    "    new-instance v2, Landroid/hardware/camera2/params/OutputConfiguration;\n\n"
                    "    invoke-direct {" + arguments + "}, "
                    "Landroid/hardware/camera2/params/OutputConfiguration;-><init>("
                    + parameters + ")V\n\n"
                    "    move-object p1, v2\n\n"
                    "    goto :try_end_0\n\n"
                    "    :lineage_stock_output_constructor")
        body = body.replace(lookup, fallback)
        # Direct constructor validation must retain the stock error wrapper.
        handler = ("    .catch Ljava/lang/IllegalArgumentException; "
                   "{:try_start_0 .. :try_end_0} :catch_1")
        if body.count(handler) != 1:
            raise ValueError(f"Unexpected stock output error handler: {field}")
        return body.replace(handler, handler + "\n"
                            "    .catch Ljava/lang/NullPointerException; "
                            "{:try_start_0 .. :try_end_0} :catch_1")

    cam_device = "smali/com/samsung/android/camera/core2/device/CamDeviceImpl.smali"
    for signature, field, parameters, arguments in (
            ("Landroid/view/Surface;I", "CONSTRUCTOR_OUTPUT_CONFIGURATION",
             "Landroid/view/Surface;", "v2, p1"),
            ("Landroid/util/Size;Ljava/lang/Class;I",
             "CONSTRUCTOR_DEFERRED_OUTPUT_CONFIGURATION",
             "Landroid/util/Size;Ljava/lang/Class;", "v2, p1, p2")):
        patch_method(cam_device, "private createOutputConfiguration("
                     + signature + ")Landroid/hardware/camera2/params/OutputConfiguration;",
                     lambda body, f=field, p=parameters, a=arguments:
                     fallback_output(body, f, p, a))

    def fallback_key(body, factory, key_type):
        missing = ("    :cond_0\n"
                   "    new-instance p0, Ljava/lang/RuntimeException;\n\n"
                   '    const-string p1, "Fail to create key."\n\n'
                   "    invoke-direct {p0, p1}, Ljava/lang/RuntimeException;-><init>(Ljava/lang/String;)V\n\n"
                   "    throw p0")
        if body.count(missing) != 1:
            raise ValueError(f"Unexpected stock key-maker fallback: {factory}")
        fallback = ("    :cond_0\n"
                    "    invoke-virtual {p1}, Lcom/samsung/android/camera/core2/local/internal/"
                    "TypeReference;->getType()Ljava/lang/reflect/Type;\n\n"
                    "    move-result-object p1\n\n"
                    "    invoke-static {p0, p1}, Lorg/lineageos/camera/compat/AndroidCompat;->"
                    + factory + "(Ljava/lang/String;Ljava/lang/reflect/Type;)"
                    + key_type + "\n\n"
                    "    move-result-object p0\n\n"
                    "    return-object p0")
        return body.replace(missing, fallback)

    pdk_util = "smali/com/samsung/android/camera/core2/local/internal/PdkUtil.smali"
    for owner in ("CameraCharacteristics", "CaptureRequest", "CaptureResult"):
        factory = "create" + owner + "Key"
        key_type = "Landroid/hardware/camera2/" + owner + "$Key;"
        signature = ("public static " + factory + "(Ljava/lang/String;"
                     "Lcom/samsung/android/camera/core2/local/internal/TypeReference;)"
                     + key_type)
        patch_method(pdk_util, signature,
                     lambda body, f=factory, k=key_type: fallback_key(body, f, k))


    def omit_aosp_thumbnail_stream(body, owner="PhotoMakerBase"):
        """Keep stock stream roles only on frameworks that support mOption."""
        assignment = (
            "    iput-object v9, v1, Lcom/samsung/android/camera/core2/maker/"
            + owner + ";->mThumbnailCbImageSize:Landroid/util/Size;")
        if (body.count(assignment) != 1
                or ":lineage_keep_thumbnail_stream" in body):
            raise ValueError("Unexpected stock thumbnail callback size assignment")
        guard = (
            "    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;"
            "->hasSamsungStreamOptions()Z\n\n"
            "    move-result v10\n\n"
            "    if-nez v10, :lineage_keep_thumbnail_stream\n\n"
            "    const/4 v9, 0x0\n\n"
            "    :lineage_keep_thumbnail_stream\n")
        return body.replace(assignment, guard + assignment)

    patch_method(
        "smali/com/samsung/android/camera/core2/maker/PhotoMakerBase.smali",
        "public declared-synchronized connectCamDevice("
        "Lcom/samsung/android/camera/core2/CamDevice;"
        "Lcom/samsung/android/camera/core2/container/DeviceConfiguration;"
        "Lcom/samsung/android/camera/core2/MakerInterface$StateCallback;"
        "Landroid/os/Handler;)V",
        omit_aosp_thumbnail_stream)
    patch_method(
        "smali/com/samsung/android/camera/core2/maker/ProPhotoMaker.smali",
        "public declared-synchronized connectCamDevice("
        "Lcom/samsung/android/camera/core2/CamDevice;"
        "Lcom/samsung/android/camera/core2/container/DeviceConfiguration;"
        "Lcom/samsung/android/camera/core2/MakerInterface$StateCallback;"
        "Landroid/os/Handler;)V",
        lambda body: omit_aosp_thumbnail_stream(body, "ProPhotoMaker"))



RELATIVE = 'smali/com/samsung/android/camera/core2/maker/MakerBase.smali'
SIGNATURE = 'public declared-synchronized takePreviewSnapShot()V'


def patch_preview_snapshot(decoded):
    path = Path(decoded) / RELATIVE
    text = path.read_text()
    pattern = re.compile(r'(?m)^\.method ' + re.escape(SIGNATURE)
                         + r'\n.*?^\.end method$', re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError('Expected one stock preview snapshot method')
    match = matches[0]
    before = ('    invoke-static {v2, v1}, '
              'Lcom/samsung/android/camera/core2/util/NativeUtils;'
              '->putByteBufferFromSurface(Landroid/view/Surface;'
              'Ljava/nio/ByteBuffer;)V')
    after = ('    iget-object v3, p0, '
             'Lcom/samsung/android/camera/core2/maker/MakerBase;'
             '->mMainPreviewSurfaceSize:Landroid/util/Size;\n\n'
             '    invoke-static {v2, v1, v3}, '
             'Lorg/lineageos/camera/compat/SurfaceCompat;'
             '->copyPreviewToNv21(Landroid/view/Surface;'
             'Ljava/nio/ByteBuffer;Landroid/util/Size;)V')
    body = match[0]
    if body.count(before) != 1 or body.count('    .locals 3\n') != 1:
        raise ValueError('Unexpected stock preview snapshot invocation/registers')
    if body.count('.catch Ljava/lang/RuntimeException; '
                  '{:try_start_3 .. :try_end_3} :catch_0') != 1:
        raise ValueError('Unexpected stock preview snapshot error callback')
    patched = body.replace('    .locals 3\n', '    .locals 4\n').replace(before, after)
    path.write_text(text[:match.start()] + patched + text[match.end():])
    return patched


HELPER = "Lorg/lineageos/camera/compat/MediaStoreCompat;"
TASK = "Lcom/sec/android/app/camera/engine/PictureProcessor$PictureSavingTask;"
PICTURE = "Lcom/sec/android/app/camera/engine/PictureProcessor;"
COMMON = "Lcom/sec/android/app/camera/engine/CommonEngine;"
LAST = "Lcom/sec/android/app/camera/engine/LastContentData;"
RECORDING = "Lcom/sec/android/app/camera/engine/RecordingManagerImpl;"


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one stock match: {old[:100]!r}")
    return text.replace(old, new, 1)


def edit_method(text, signature, transform):
    pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                         + r"\n.*?^\.end method$", re.S)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"Expected one method: {signature}")
    match = matches[0]
    return text[:match.start()] + transform(match[0]) + text[match.end():]


def save_wrapper():
    return f""".method private saveImage()Z
    .locals 3

    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I
    const/16 v1, 0x1d
    if-gt v0, v1, :modern
    invoke-direct {{p0}}, {TASK}->saveImageStock()Z
    move-result v0
    return v0

    :modern
    :try_start
    invoke-direct {{p0}}, {TASK}->saveImageStock()Z
    move-result v0
    :try_end
    .catch Ljava/lang/RuntimeException; {{:try_start .. :try_end}} :failed
    if-eqz v0, :cleanup
    return v0

    :failed
    move-exception v0
    const-string v1, "PictureProcessor"
    const-string v2, "Could not save the captured image to MediaStore"
    invoke-static {{v1, v2, v0}}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :cleanup
    iget-object v0, p0, {TASK}->this$0:{PICTURE}
    invoke-static {{v0}}, {PICTURE}->access$1200({PICTURE})Landroid/content/ContentResolver;
    move-result-object v0
    iget-object v1, p0, {TASK}->mUri:Landroid/net/Uri;
    invoke-static {{v0, v1}}, {HELPER}->deleteFailedSave(Landroid/content/ContentResolver;Landroid/net/Uri;)V
    const/4 v1, 0x0
    iput-object v1, p0, {TASK}->mUri:Landroid/net/Uri;
    iget-object v0, p0, {TASK}->this$0:{PICTURE}
    invoke-static {{v0}}, {PICTURE}->access$300({PICTURE}){COMMON}
    move-result-object v0
    invoke-virtual {{v0}}, {COMMON}->getLastContentData()Lcom/sec/android/app/camera/interfaces/Engine$ContentData;
    move-result-object v0
    check-cast v0, {LAST}
    invoke-virtual {{v0}}, {LAST}->clear()V
    const/4 v0, 0x0
    return v0
.end method"""


def discard_recording():
    return f""".method private discardPendingRecording()V
    .locals 3
    iget-object v0, p0, {RECORDING}->mCameraContext:Lcom/sec/android/app/camera/interfaces/CameraContext;
    invoke-interface {{v0}}, Lcom/sec/android/app/camera/interfaces/CameraContext;->getContext()Landroid/content/Context;
    move-result-object v0
    invoke-virtual {{v0}}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0
    iget-object v1, p0, {RECORDING}->mLastContentDataForRecording:{LAST}
    invoke-virtual {{v1}}, {LAST}->getContentUriForWriting()Landroid/net/Uri;
    move-result-object v2
    invoke-static {{v0, v2}}, {HELPER}->deleteFailedSave(Landroid/content/ContentResolver;Landroid/net/Uri;)V
    invoke-virtual {{v1}}, {LAST}->clear()V
    return-void
.end method"""


def start_guard(label):
    listener = "Lcom/sec/android/app/camera/interfaces/RecordingManager$RecordingManagerEventListener;"
    return f"""invoke-direct {{p0}}, {RECORDING}->tempInsertToDB()Z
    move-result v0
    if-nez v0, :{label}
    iget-object v0, p0, {RECORDING}->mRecordingManagerEventListener:{listener}
    if-eqz v0, :{label}_return
    invoke-interface {{v0}}, {listener}->onCancelRecordingRequested()V
    :{label}_return
    return-void
    :{label}"""


def patch_media_store(decoded):
    decoded = Path(decoded)
    task = decoded / "smali_classes2/com/sec/android/app/camera/engine/PictureProcessor$PictureSavingTask.smali"
    stock = task.read_text()

    def temp(method):
        # Drop the first Samsung metadata insert and group link, rather than
        # redirecting that insert to create an accidental second image row.
        start = method.index("    .line 1199\n")
        end = method.index("    sget-object v4, Landroid/provider/MediaStore$Images$Media;->EXTERNAL_CONTENT_URI")
        method = method[:start] + method[end:]
        method = replace_once(method,
                "invoke-virtual {v5, v4, p1}, Landroid/content/ContentResolver;->insert(Landroid/net/Uri;Landroid/content/ContentValues;)Landroid/net/Uri;",
                f"invoke-static {{v5, v4, p1}}, {HELPER}->insertPending(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;)Landroid/net/Uri;")
        # Reading and writing refer to the same real row on Android.
        marker = f"    iput-object p1, p0, {TASK}->mUri:Landroid/net/Uri;"
        return replace_once(method, marker, marker + "\n\n    move-object v3, p1")

    stock = edit_method(stock, "private tempInsertToDB(Landroid/content/ContentValues;)V", temp)
    stock = edit_method(stock, "private updateToDB(Landroid/content/ContentValues;)V",
            lambda m: replace_once(m,
                "invoke-virtual {v2, p0, p1, v1, v1}, Landroid/content/ContentResolver;->update(Landroid/net/Uri;Landroid/content/ContentValues;Ljava/lang/String;[Ljava/lang/String;)I",
                f"invoke-static {{v2, p0, p1}}, {HELPER}->publish(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;)I"))
    stock = edit_method(stock, "private saveImage()Z",
            lambda m: replace_once(replace_once(m,
                ".method private saveImage()Z", ".method private saveImageStock()Z"),
                "Lcom/sec/android/app/camera/util/ImageUtils;->writeImageToUri(Landroid/content/ContentResolver;Landroid/net/Uri;Ljava/nio/ByteBuffer;)Z",
                f"{HELPER}->writeImage(Landroid/content/ContentResolver;Landroid/net/Uri;Ljava/nio/ByteBuffer;)Z")
            + "\n\n" + save_wrapper())
    task.write_text(stock)

    recording = decoded / "smali_classes2/com/sec/android/app/camera/engine/RecordingManagerImpl.smali"
    stock = recording.read_text()

    def video_temp(method):
        method = replace_once(method, ".method private tempInsertToDB()V",
                ".method private tempInsertToDB()Z")
        start = method.index("    sget-object v3, Lcom/sec/android/app/camera/util/ImageUtils;->DB_SEC_MEDIA_URI")
        end = method.index('    const-string v4, "content://media/external/video/media"', start)
        method = method[:start] + method[end:]
        method = replace_once(method,
                "invoke-virtual {v5, v4, v0}, Landroid/content/ContentResolver;->insert(Landroid/net/Uri;Landroid/content/ContentValues;)Landroid/net/Uri;",
                f"invoke-static {{v5, v4, v0}}, {HELPER}->insertPending(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;)Landroid/net/Uri;")
        marker = "    move-result-object v0\n\n    .line 2533"
        method = replace_once(method, marker,
                "    move-result-object v0\n\n    move-object v3, v0\n\n    .line 2533")
        # The requested attach URI does not need a database row.
        method = replace_once(method, "    return-void\n\n    :cond_0",
                "    const/4 v0, 0x1\n\n    return v0\n\n    :cond_0")
        method = replace_once(method, "    return-void\n\n    :cond_3",
                "    const/4 v0, 0x1\n\n    return v0\n\n    :cond_3")
        # Existing errors remain logged, but cannot advance without a real URI.
        success = "    goto :goto_3\n\n    :catch_0"
        method = replace_once(method, success,
                "    const/4 v0, 0x1\n\n    return v0\n\n    :catch_0")
        method = replace_once(method, "    return-void\n.end method",
                "    const/4 v0, 0x0\n\n    return v0\n.end method")
        return method

    stock = edit_method(stock, "private tempInsertToDB()V", video_temp)

    def video_update(method):
        method = replace_once(method, ".method private updateToDB()V",
                ".method private updateToDB()Z")
        method = replace_once(method,
                "invoke-virtual {v0, v4, v2, v5, v5}, Landroid/content/ContentResolver;->update(Landroid/net/Uri;Landroid/content/ContentValues;Ljava/lang/String;[Ljava/lang/String;)I",
                f"invoke-static {{v0, v4, v2}}, {HELPER}->publish(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;)I")
        # No broadcast or saved event after either of the existing DB catches.
        caught = method.index("    :catch_1\n")
        published = method.index("    .line 2725\n", caught)
        errors = method[caught:published].replace("    goto :goto_1", "    goto :save_failed")
        method = method[:caught] + errors + f"""    goto :save_failed

    :save_failed
    invoke-direct {{p0}}, {RECORDING}->discardPendingRecording()V
    const/4 v0, 0x0
    return v0

""" + method[published:]
        return replace_once(method, "    return-void\n\n    .line 2710",
                "    const/4 v0, 0x1\n\n    return v0\n\n    .line 2710")

    stock = edit_method(stock, "private updateToDB()V", video_update)
    stock = edit_method(stock, "private registerVideo(Z)V", lambda m: replace_once(m,
            f"invoke-direct {{p0}}, {RECORDING}->updateToDB()V",
            f"invoke-direct {{p0}}, {RECORDING}->updateToDB()Z\n\n    move-result v1\n\n    if-nez v1, :goto_1\n\n    return-void"))
    for signature in ("public startVideoRecording()V", "public startSuperSlowMotionRecording(I)V"):
        stock = edit_method(stock, signature, lambda m: replace_once(m,
                f"invoke-direct {{p0}}, {RECORDING}->tempInsertToDB()V",
                start_guard("pending_media_ready")))
    stock += "\n\n" + discard_recording() + "\n"
    recording.write_text(stock)

    latest = decoded / "smali/com/sec/android/app/camera/LatestMediaContent.smali"
    stock = latest.read_text()
    query = "Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;"
    if stock.count(query) != 4:
        raise ValueError("Expected four stock latest-media queries")
    stock = re.sub(r"invoke-virtual/range (\{[^}]+\}), " + re.escape(query),
            rf"invoke-static/range \1, {HELPER}->queryLatest(Landroid/content/ContentResolver;Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;", stock)
    # The Files collection shares genuine image/video IDs and is suitable for
    # the stock latest-media UI. Leave Samsung globals used by optional modes.
    stock = stock.replace("Lcom/sec/android/app/camera/util/ImageUtils;->DB_SEC_MEDIA_URI:Landroid/net/Uri;",
            "Lcom/sec/android/app/camera/util/ImageUtils;->DB_MEDIA_URI:Landroid/net/Uri;")
    stock = stock.replace("content://secmedia/media/", "content://media/external/file/")
    latest.write_text(stock)



def patch_recording_orientation(decoded):
    def edit(text, signature, transform):
        pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                             + r"\n.*?^\.end method$", re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError(f"Expected one recorder method: {signature}")
        match = matches[0]
        return text[:match.start()] + transform(match[0]) + text[match.end():]

    def replace(body, before, after):
        if body.count(before) != 1:
            raise ValueError("Unexpected stock recorder orientation sequence")
        return body.replace(before, after, 1)

    root = Path(decoded) / "smali_classes2/com/sec/android/app/camera/engine"
    recording_path = root / "RecordingManagerImpl.smali"
    start_path = root / "request/StartVideoRecordingRequest.smali"
    prepare_before = """    :try_start_5
    iget-object v0, p0, Lcom/sec/android/app/camera/engine/RecordingManagerImpl;->mMediaRecorder:Landroid/media/MediaRecorder;

    invoke-virtual {v0}, Landroid/media/MediaRecorder;->prepare()V"""
    prepare_after = """    :try_start_5
    invoke-virtual {p0}, Lcom/sec/android/app/camera/engine/RecordingManagerImpl;->updateOrientationHint()V

    iget-object v0, p0, Lcom/sec/android/app/camera/engine/RecordingManagerImpl;->mMediaRecorder:Landroid/media/MediaRecorder;

    invoke-virtual {v0}, Landroid/media/MediaRecorder;->prepare()V"""
    start_before = """    :try_start_0
    iget-object v3, p0, Lcom/sec/android/app/camera/engine/request/StartVideoRecordingRequest;->mEngine:Lcom/sec/android/app/camera/interfaces/InternalEngine;

    invoke-interface {v3}, Lcom/sec/android/app/camera/interfaces/InternalEngine;->getOrientationForCapture()I

    move-result v3

    invoke-virtual {v1, v3}, Landroid/media/MediaRecorder;->setOrientationHint(I)V

    .line 57
    invoke-virtual {v1}, Landroid/media/MediaRecorder;->start()V"""
    start_after = """    :try_start_0
    .line 57
    invoke-virtual {v1}, Landroid/media/MediaRecorder;->start()V"""
    recording_text = edit(recording_path.read_text(),
                          "public prepareMediaRecorder()V",
                          lambda body: replace(body, prepare_before, prepare_after))
    start_text = edit(start_path.read_text(), "execute()V",
                      lambda body: replace(body, start_before, start_after))
    # Validate both inputs before writing either staged file.
    recording_path.write_text(recording_text)
    start_path.write_text(start_text)
    return [str(recording_path), str(start_path)]



SHUTTER_CLASS = "Lcom/samsung/android/camera/core2/device/CamDevicePicCaptureCallback;"
SHUTTER_DEVICE = "Lcom/samsung/android/camera/core2/device/CamDeviceImpl;"
SHUTTER_LAMBDA = ("Lcom/samsung/android/camera/core2/device/"
          "-$$Lambda$CamDevicePicCaptureCallback$uwUyYzvBnBLm6R5uav8KhU5U088;")


def shutter_replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one match: {old[:120]!r}")
    return text.replace(old, new, 1)


def patch_single_photo_shutter_text(text):
    text = shutter_replace_once(text, "# direct methods\n", "# direct methods\n")
    text = shutter_replace_once(text,
        ".field private final mPictureCallback:",
        ".field private volatile mIsShutterCallbackForwarded:Z\n\n"
        ".field private final mPictureCallback:")

    # Both original handler runnables retain their signatures and route through
    # one synchronized guard. Every waiter is released, including late duplicates.
    old = f"""    iget-object p0, p0, {SHUTTER_CLASS}->mPictureCallback:Lcom/samsung/android/camera/core2/CamDevice$PictureCallback;

    invoke-interface {{p0, p1}}, Lcom/samsung/android/camera/core2/CamDevice$PictureCallback;->onShutter(Ljava/lang/Long;)V

    .line 170
    invoke-virtual {{p2}}, Ljava/util/concurrent/CountDownLatch;->countDown()V"""
    text = shutter_replace_once(text, old, f"""    invoke-direct {{p0, p1, p2}}, {SHUTTER_CLASS}->dispatchShutterOnce(Ljava/lang/Long;Ljava/util/concurrent/CountDownLatch;)V""")
    old = f"""    iget-object p0, p0, {SHUTTER_CLASS}->mPictureCallback:Lcom/samsung/android/camera/core2/CamDevice$PictureCallback;

    invoke-static {{p1, p2}}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;

    move-result-object p1

    invoke-interface {{p0, p1}}, Lcom/samsung/android/camera/core2/CamDevice$PictureCallback;->onShutter(Ljava/lang/Long;)V

    .line 256
    invoke-virtual {{p3}}, Ljava/util/concurrent/CountDownLatch;->countDown()V"""
    text = shutter_replace_once(text, old, f"""    invoke-static {{p1, p2}}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;

    move-result-object p1

    invoke-direct {{p0, p1, p3}}, {SHUTTER_CLASS}->dispatchShutterOnce(Ljava/lang/Long;Ljava/util/concurrent/CountDownLatch;)V""")
    text = shutter_replace_once(text,
        "    if-eqz p2, :cond_1\n\n    .line 94\n",
        f"    if-eqz p2, :cond_1\n\n"
        f"    invoke-direct {{p0, p2}}, {SHUTTER_CLASS}->completeMissingShutter(Ljava/lang/Long;)V\n\n"
        "    .line 94\n")

    methods = f"""
.method private declared-synchronized claimShutter()Z
    .locals 2

    monitor-enter p0
    :compat_claim_try
    iget-boolean v0, p0, {SHUTTER_CLASS}->mIsShutterCallbackForwarded:Z
    if-nez v0, :compat_claim_duplicate

    const/4 v0, 0x1
    iput-boolean v0, p0, {SHUTTER_CLASS}->mIsShutterCallbackForwarded:Z
    monitor-exit p0
    return v0

    :compat_claim_duplicate
    const/4 v0, 0x0
    monitor-exit p0
    return v0
    :compat_claim_try_end
    .catchall {{:compat_claim_try .. :compat_claim_try_end}} :compat_claim_error

    :compat_claim_error
    move-exception v1
    monitor-exit p0
    throw v1
.end method

.method private dispatchShutterOnce(Ljava/lang/Long;Ljava/util/concurrent/CountDownLatch;)V
    .locals 2

    :compat_shutter_try
    invoke-direct {{p0}}, {SHUTTER_CLASS}->claimShutter()Z
    move-result v0
    if-eqz v0, :compat_shutter_done

    iget-object v0, p0, {SHUTTER_CLASS}->mPictureCallback:Lcom/samsung/android/camera/core2/CamDevice$PictureCallback;
    invoke-interface {{v0, p1}}, Lcom/samsung/android/camera/core2/CamDevice$PictureCallback;->onShutter(Ljava/lang/Long;)V

    :compat_shutter_done
    :compat_shutter_try_end
    .catchall {{:compat_shutter_try .. :compat_shutter_try_end}} :compat_shutter_error

    invoke-virtual {{p2}}, Ljava/util/concurrent/CountDownLatch;->countDown()V
    return-void

    :compat_shutter_error
    move-exception v1
    invoke-virtual {{p2}}, Ljava/util/concurrent/CountDownLatch;->countDown()V
    throw v1
.end method

.method private completeMissingShutter(Ljava/lang/Long;)V
    .locals 5

    iget-boolean v0, p0, {SHUTTER_CLASS}->mIsShutterCallbackForwarded:Z
    if-nez v0, :compat_complete_done

    iget-object v0, p0, {SHUTTER_CLASS}->mCamDeviceImpl:{SHUTTER_DEVICE}
    invoke-virtual {{v0}}, {SHUTTER_DEVICE}->getSendShutterHandler()Landroid/os/Handler;
    move-result-object v0
    if-eqz v0, :compat_complete_post_failed

    new-instance v1, Ljava/util/concurrent/CountDownLatch;
    const/4 v2, 0x1
    invoke-direct {{v1, v2}}, Ljava/util/concurrent/CountDownLatch;-><init>(I)V

    new-instance v2, {SHUTTER_LAMBDA}
    invoke-direct {{v2, p0, p1, v1}}, {SHUTTER_LAMBDA}-><init>({SHUTTER_CLASS}Ljava/lang/Long;Ljava/util/concurrent/CountDownLatch;)V
    invoke-virtual {{v0, v2}}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z
    move-result v0
    if-eqz v0, :compat_complete_post_failed

    iget-object v0, p0, {SHUTTER_CLASS}->TAG:Lcom/samsung/android/camera/core2/util/CLog$Tag;
    const-string v2, "PicCaptureCallback onCaptureCompleted - using completed capture timestamp for missing shutter callback"
    invoke-static {{v0, v2}}, Lcom/samsung/android/camera/core2/util/CLog;->i(Lcom/samsung/android/camera/core2/util/CLog$Tag;Ljava/lang/String;)V

    :compat_complete_wait
    const-wide/16 v2, 0x5
    sget-object v4, Ljava/util/concurrent/TimeUnit;->SECONDS:Ljava/util/concurrent/TimeUnit;
    invoke-virtual {{v1, v2, v3, v4}}, Ljava/util/concurrent/CountDownLatch;->await(JLjava/util/concurrent/TimeUnit;)Z
    move-result v1
    if-nez v1, :compat_complete_done

    const-string v2, "PicCaptureCallback onCaptureCompleted - missing shutter callback did not finish within 5 sec"
    invoke-static {{v0, v2}}, Lcom/samsung/android/camera/core2/util/CLog;->e(Lcom/samsung/android/camera/core2/util/CLog$Tag;Ljava/lang/String;)V
    :compat_complete_wait_end
    .catch Ljava/lang/InterruptedException; {{:compat_complete_wait .. :compat_complete_wait_end}} :compat_complete_interrupted
    goto :compat_complete_done

    :compat_complete_interrupted
    move-exception v1
    invoke-static {{}}, Ljava/lang/Thread;->currentThread()Ljava/lang/Thread;
    move-result-object v1
    invoke-virtual {{v1}}, Ljava/lang/Thread;->interrupt()V
    const-string v2, "PicCaptureCallback onCaptureCompleted - interrupted waiting for missing shutter callback"
    invoke-static {{v0, v2}}, Lcom/samsung/android/camera/core2/util/CLog;->e(Lcom/samsung/android/camera/core2/util/CLog$Tag;Ljava/lang/String;)V
    goto :compat_complete_done

    :compat_complete_post_failed
    iget-object v0, p0, {SHUTTER_CLASS}->TAG:Lcom/samsung/android/camera/core2/util/CLog$Tag;
    const-string v2, "PicCaptureCallback onCaptureCompleted - cannot post missing shutter callback"
    invoke-static {{v0, v2}}, Lcom/samsung/android/camera/core2/util/CLog;->e(Lcom/samsung/android/camera/core2/util/CLog$Tag;Ljava/lang/String;)V

    :compat_complete_done
    return-void
.end method

"""
    return shutter_replace_once(text, "# virtual methods\n", methods + "# virtual methods\n")


def patch_single_photo_shutter(root):
    path = root / ("smali/com/samsung/android/camera/core2/device/"
                   "CamDevicePicCaptureCallback.smali")
    path.write_text(patch_single_photo_shutter_text(path.read_text()))



def adapt_optional_scene_toast(root):
    """Keep photo callbacks usable without optional scene optimizer views."""
    import re

    path = root / "smali_classes2/com/sec/android/app/camera/shootingmode/Photo$IntelligentManager.smali"
    OWNER = "Lcom/sec/android/app/camera/shootingmode/Photo$IntelligentManager;"
    text = path.read_text()

    def replace_once(text, old, new):
        if text.count(old) != 1:
            raise ValueError('Expected one stock optional scene toast match: ' + old[:100])
        return text.replace(old, new, 1)

    match = re.search(r'(?m)^\.method private onActivityTouchEvent\(Landroid/view/MotionEvent;\)Z\n.*?^\.end method$', text, re.S)
    if match is None:
        raise ValueError('Missing stock IntelligentManager touch method')
    method = match[0]
    method = replace_once(method,
        f'    :cond_0\n    iget-object p1, p0, {OWNER}->mSceneOptimizerToast:Lcom/sec/android/app/camera/widget/gl/SceneOptimizerToast;\n',
        f'    :cond_0\n    iget-object p1, p0, {OWNER}->mSceneOptimizerToast:Lcom/sec/android/app/camera/widget/gl/SceneOptimizerToast;\n\n    if-eqz p1, :cond_1\n')
    method = replace_once(method,
        f'    :cond_3\n    iget-object p1, p0, {OWNER}->mSceneOptimizerToast:Lcom/sec/android/app/camera/widget/gl/SceneOptimizerToast;\n',
        f'    :cond_3\n    iget-object p1, p0, {OWNER}->mSceneOptimizerToast:Lcom/sec/android/app/camera/widget/gl/SceneOptimizerToast;\n\n    if-eqz p1, :compat_night_popup_down\n')
    method = replace_once(method,
        f'    if-nez p1, :cond_4\n\n    iget-object p0, p0, {OWNER}->this$0:',
        f'    if-nez p1, :cond_4\n\n    :compat_night_popup_down\n    iget-object p0, p0, {OWNER}->this$0:')
    text = text[:match.start()] + method + text[match.end():]

    # These callbacks are registered even when scene recognition is disabled.
    # Keep their state/guide updates and skip only the absent optional view.
    for signature in (
            "public onTouchEvSliderVisibilityChanged(Z)V",
            "public onPopupVisibilityChanged(Lcom/sec/android/app/camera/"
            "interfaces/PopupLayoutController$PopupId;Z)V"):
        pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                             + r"\n.*?^\.end method$", re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError("Missing stock optional scene callback: " + signature)
        match = matches[0]
        method = match[0]
        if len(re.findall(r"(?m)^    :goto_0$", method)) != 1:
            raise ValueError("Unexpected stock scene callback exit: " + signature)
        call = ("    invoke-virtual {p0}, Lcom/sec/android/app/camera/"
                "widget/gl/SceneDetectView;->hide()V")
        method = replace_once(method, call,
                              "    if-eqz p0, :goto_0\n\n" + call)
        text = text[:match.start()] + method + text[match.end():]
    photo_path = root / "smali_classes2/com/sec/android/app/camera/shootingmode/Photo.smali"
    photo_text = photo_path.read_text()
    for signature, calls in (
            ("public onShow(Lcom/sec/android/app/camera/interfaces/MenuBase;)V", (
                ("p1", "SceneDetectView", "compat_menu_scene_hidden"),
                ("p1", "SceneOptimizerToast", "compat_menu_toast_hidden"))),
            ("public onBurstCaptureStarted()V", (
                ("v0", "SceneDetectView", "compat_burst_scene_hidden"),))):
        pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                             + r"\n.*?^\.end method$", re.S)
        matches = list(pattern.finditer(photo_text))
        if len(matches) != 1:
            raise ValueError("Missing stock optional Photo view callback: " + signature)
        match = matches[0]
        method = match[0]
        for register, view, label in calls:
            if label in method:
                raise ValueError("Optional Photo view callback already guarded")
            call = ("    invoke-virtual {" + register + "}, Lcom/sec/android/"
                    "app/camera/widget/gl/" + view + ";->hide()V")
            method = replace_once(method, call,
                                  "    if-eqz " + register + ", :" + label
                                  + "\n\n" + call + "\n\n    :" + label)
        photo_text = photo_text[:match.start()] + method + photo_text[match.end():]
    path.write_text(text)
    photo_path.write_text(photo_text)


def patch_front_camera_device_id(decoded):
    """Resolve only the stock dynamic front device alias at translation."""
    path = Path(decoded) / (
        "smali_classes2/com/sec/android/app/camera/engine/request/CameraHolder.smali")
    text = path.read_text()
    field = ".field private mCompatCameraContext:Landroid/content/Context;"
    anchor = ".field private mCamDeviceManager:Lcom/samsung/android/camera/core2/device/CamDeviceManager;"
    if field in text or text.count(anchor) != 1:
        raise ValueError("Unexpected stock CameraHolder fields")
    text = text.replace(anchor, anchor + "\n\n" + field)

    def rewrite(signature, change):
        nonlocal text
        pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                             + r"\n.*?^\.end method$", re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError("Expected one stock CameraHolder method: " + signature)
        match = matches[0]
        body = change(match[0])
        text = text[:match.start()] + body + text[match.end():]

    def save_context(body):
        constructor = "    invoke-direct {p0}, Ljava/lang/Object;-><init>()V"
        if body.count(constructor) != 1:
            raise ValueError("Unexpected stock CameraHolder constructor")
        return body.replace(constructor, constructor + "\n\n"
            "    iput-object p1, p0, Lcom/sec/android/app/camera/engine/request/"
            "CameraHolder;->mCompatCameraContext:Landroid/content/Context;")

    def resolve_id(body):
        locals_line = "    .locals 2"
        if body.count(locals_line) != 1 or body.count("    const/4 p0, 0x3") != 1:
            raise ValueError("Unexpected stock CameraHolder device-ID translation")
        prefix = """

    const/4 v0, 0x3
    if-ne p1, v0, :lineage_stock_device_id
    iget-object v0, p0, Lcom/sec/android/app/camera/engine/request/CameraHolder;->mCompatCameraContext:Landroid/content/Context;
    invoke-static {v0, p1}, Lorg/lineageos/camera/compat/CameraDeviceCompat;->resolveFrontCameraDeviceId(Landroid/content/Context;I)I
    move-result p1
    :lineage_stock_device_id
"""
        return body.replace(locals_line, locals_line + prefix)

    rewrite("public constructor <init>(Landroid/content/Context;)V", save_context)
    rewrite("private getCameraDeviceId(I)I", resolve_id)
    path.write_text(text)


def patch_gallery_viewer(decoded):
    """Use Android media viewers for normal gallery launches."""
    import re

    path = decoded / "smali/com/sec/android/app/camera/Camera.smali"
    text = path.read_text()
    pattern = re.compile(r'(?m)^\.method public launchGallery\(Z\)Z\n.*?^\.end method$', re.S)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("Expected one stock gallery launch method")
    match = matches[0]
    body = match[0]
    old = """    invoke-interface {v4}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->isSecureCamera()Z

    move-result v4

    invoke-direct {p0, v0, v4}, Lcom/sec/android/app/camera/Camera;->updateGalleryIntent(Landroid/content/Intent;Z)Z"""
    new = """    invoke-interface {v4}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->isSecureCamera()Z

    move-result v4

    move v7, v4

    invoke-direct {p0, v0, v4}, Lcom/sec/android/app/camera/Camera;->updateGalleryIntent(Landroid/content/Intent;Z)Z"""
    if body.count(old) != 1:
        raise ValueError("Unexpected stock gallery secure-mode selection")
    body = body.replace(old, new, 1)
    success = "    :cond_1\n    new-instance v4, Ljava/lang/StringBuilder;"
    review = """    :cond_1
    # The update succeeded; v7 still holds its secure-camera argument.
    # Keep the stock restricted gallery path for secure camera launches.
    if-nez v7, :compat_gallery_review_ready
    const/4 v5, 0x0
    invoke-virtual {v0, v5}, Landroid/content/Intent;->setComponent(Landroid/content/ComponentName;)Landroid/content/Intent;
    const/4 v5, 0x1
    invoke-virtual {v0, v5}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;
    invoke-static {p0, v0, v7}, Lorg/lineageos/camera/compat/GalleryCompat;->prepareReviewIntent(Landroid/content/Context;Landroid/content/Intent;Z)V
    :compat_gallery_review_ready

    new-instance v4, Ljava/lang/StringBuilder;"""
    if body.count(success) != 1:
        raise ValueError("Unexpected stock successful gallery launch")
    body = body.replace(success, review, 1)
    path.write_text(text[:match.start()] + body + text[match.end():])


def patch_recording_progress(decoded: Path) -> None:
    owner = "Lcom/sec/android/app/camera/engine/RecordingManagerImpl;"
    clock = "Lorg/lineageos/camera/compat/RecordingClock;"
    state = "Lcom/sec/android/app/camera/interfaces/RecordingManager$RecordingState;"
    source = decoded / "smali_classes2/com/sec/android/app/camera/engine/RecordingManagerImpl.smali"
    text = source.read_text()
    if "mCompatRecordingClock:" in text:
        raise ValueError("Recording progress fallback already applied")

    def method(signature: str, change) -> None:
        nonlocal text
        pattern = re.compile(r"(?m)^\.method [^\n]* " + re.escape(signature)
                             + r"\n[\s\S]*?^\.end method$")
        found = list(pattern.finditer(text))
        if len(found) != 1:
            raise ValueError(f"Expected one method {signature}, got {len(found)}")
        old = found[0].group()
        new = change(old)
        if new == old:
            raise ValueError(f"No change to {signature}")
        text = text[:found[0].start()] + new + text[found[0].end():]

    def entry(body: str, code: str) -> str:
        return re.sub(r"(    \.locals \d+\n)", r"\1\n" + code, body, count=1)

    def once(body: str, old: str, new: str) -> str:
        if body.count(old) != 1:
            raise ValueError(f"Expected one anchor: {old}")
        return body.replace(old, new, 1)

    text = once(text, "# instance fields\n", "# instance fields\n"
                f".field private final mCompatRecordingClock:{clock}\n\n")
    init = (f"    new-instance v0, {clock}\n"
            f"    invoke-direct {{v0}}, {clock}-><init>()V\n"
            f"    iput-object v0, p0, {owner}->mCompatRecordingClock:{clock}\n\n")
    method("<init>(Lcom/sec/android/app/camera/engine/CommonEngine;Lcom/sec/android/app/camera/engine/AeAfManagerImpl;)V",
           lambda b: once(b, "    return-void", init + "    return-void"))

    method("onRecordingStarted()V", lambda b: entry(b,
           f"    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}\n"
           f"    invoke-virtual {{v0}}, {clock}->start()V\n"))
    method("onRecordingPaused()V", lambda b: entry(b,
           f"    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}\n"
           f"    invoke-virtual {{v0}}, {clock}->pause()V\n"
           f"    invoke-direct {{p0}}, {owner}->updateCompatRecordingTime()V\n"))
    method("onRecordingResumed()V", lambda b: entry(b,
           f"    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}\n"
           f"    invoke-virtual {{v0}}, {clock}->resume()V\n"))

    for signature in ["onRecordingStopped()V", "onRecordingCancelled()V",
                      "releaseMediaRecorder()V", "resetMediaRecorder()V"]:
        method(signature, lambda b: entry(b,
               f"    invoke-direct {{p0}}, {owner}->finishCompatRecordingClock()V\n"))

    for signature in ["access$100(Lcom/sec/android/app/camera/engine/RecordingManagerImpl;)J",
                      "getCurrentRecordingFileTimeInMs()J",
                      "getCurrentRecordingFileTimeInSecond()J"]:
        method(signature, lambda b: entry(b,
               f"    invoke-direct {{p0}}, {owner}->updateCompatRecordingTime()V\n"))

    # Preserve the manager receiver until STARTED has reached the UI, then start
    # the existing stock timer. The helper rejects stale release/cancel callbacks.
    def started_ui(body: str) -> str:
        body = once(body, ".locals 1", ".locals 2")
        body = once(body,
                    f"iget-object p0, p0, {owner}->mRecordingManagerEventListener:",
                    f"iget-object v1, p0, {owner}->mRecordingManagerEventListener:")
        body = once(body, "if-eqz p0, :cond_0", "if-eqz v1, :cond_0")
        body = once(body, "invoke-interface {p0, v0}", "invoke-interface {v1, v0}")
        return once(body, "    :cond_0\n    return-void",
                    "    :cond_0\n"
                    f"    invoke-direct {{p0}}, {owner}->startCompatRecordingTickTimer()V\n"
                    "    return-void")
    method("lambda$onRecordingStarted$7$RecordingManagerImpl()V", started_ui)

    # A real next-file notification keeps the stock previous-file total. Start
    # the new clock only after its old duration is folded into that total.
    def rollover(body: str) -> str:
        body = entry(body, f"    invoke-direct {{p0}}, {owner}->updateCompatRecordingTime()V\n")
        anchor = f"    iput-wide v0, p0, {owner}->mCurrentRecordingFileTimeInMs:J"
        return once(body, anchor, anchor + "\n\n"
                    f"    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}\n"
                    f"    invoke-virtual {{v0}}, {clock}->rollover()V")
    method("onNextOutputFileStarted()V", rollover)

    # onInfo(901) may also request the timer on another framework; keep one chain.
    def stock_timer(body: str) -> str:
        body = entry(body,
                     f"    invoke-virtual {{p0}}, {owner}->isCompatRecordingTickActive()Z\n"
                     "    move-result v0\n"
                     "    if-nez v0, :compat_timer_active\n"
                     "    return-void\n"
                     "    :compat_timer_active\n")
        return once(body,
                    "    invoke-virtual {v0, v1}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z",
                    "    invoke-virtual {v0, v1}, Landroid/os/Handler;->removeCallbacks(Ljava/lang/Runnable;)V\n\n"
                    "    invoke-virtual {v0, v1}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z")
    method("startRecordingTickTimer()V", stock_timer)

    text += f"""

# AOSP recorder progress fallback; does not synthesize recorder success events.
.method private updateCompatRecordingTime()V
    .locals 3

    iget-object v0, p0, {owner}->mRecordingState:{state}
    sget-object v1, {state}->IDLE:{state}
    if-eq v0, v1, :compat_time_done
    sget-object v1, {state}->STARTING:{state}
    if-eq v0, v1, :compat_time_done
    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}
    invoke-virtual {{v0}}, {clock}->elapsedMillis()J
    move-result-wide v1
    iput-wide v1, p0, {owner}->mCurrentRecordingFileTimeInMs:J
    :compat_time_done
    return-void
.end method

.method private finishCompatRecordingClock()V
    .locals 5

    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}
    invoke-virtual {{v0}}, {clock}->isActive()Z
    move-result v1
    if-eqz v1, :compat_finish_remove
    invoke-virtual {{v0}}, {clock}->finish()V
    invoke-virtual {{v0}}, {clock}->elapsedMillis()J
    move-result-wide v1
    iput-wide v1, p0, {owner}->mCurrentRecordingFileTimeInMs:J
    iget-wide v3, p0, {owner}->mPreviousRecordingTimeInMs:J
    add-long/2addr v1, v3
    iput-wide v1, p0, {owner}->mTotalRecordingTimeInMs:J
    :compat_finish_remove
    iget-object v0, p0, {owner}->mCameraContext:Lcom/sec/android/app/camera/interfaces/CameraContext;
    invoke-interface {{v0}}, Lcom/sec/android/app/camera/interfaces/CameraContext;->getMainHandler()Landroid/os/Handler;
    move-result-object v0
    iget-object v1, p0, {owner}->mRecordingTickRunnable:Ljava/lang/Runnable;
    invoke-virtual {{v0, v1}}, Landroid/os/Handler;->removeCallbacks(Ljava/lang/Runnable;)V
    return-void
.end method

.method public isCompatRecordingTickActive()Z
    .locals 2

    iget-object v0, p0, {owner}->mRecordingState:{state}
    sget-object v1, {state}->IDLE:{state}
    if-eq v0, v1, :compat_tick_inactive
    sget-object v1, {state}->STOPPING:{state}
    if-eq v0, v1, :compat_tick_inactive
    iget-object v0, p0, {owner}->mCompatRecordingClock:{clock}
    invoke-virtual {{v0}}, {clock}->isActive()Z
    move-result v0
    return v0
    :compat_tick_inactive
    const/4 v0, 0x0
    return v0
.end method

.method private startCompatRecordingTickTimer()V
    .locals 1

    invoke-virtual {{p0}}, {owner}->isCompatRecordingTickActive()Z
    move-result v0
    if-eqz v0, :compat_start_done
    iget-object v0, p0, {owner}->mRecordingManagerEventListener:Lcom/sec/android/app/camera/interfaces/RecordingManager$RecordingManagerEventListener;
    if-eqz v0, :compat_start_done
    invoke-direct {{p0}}, {owner}->startRecordingTickTimer()V
    :compat_start_done
    return-void
.end method
"""
    source.write_text(text)

    tick = source.with_name("RecordingManagerImpl$1.smali")
    body = tick.read_text()
    guard = (f"    iget-object v0, p0, Lcom/sec/android/app/camera/engine/RecordingManagerImpl$1;->this$0:{owner}\n"
             f"    invoke-virtual {{v0}}, {owner}->isCompatRecordingTickActive()Z\n"
             "    move-result v0\n"
             "    if-nez v0, :compat_tick_run\n"
             "    return-void\n"
             "    :compat_tick_run\n")
    body = once(body, ".method public run()V\n    .locals 8\n",
                ".method public run()V\n    .locals 8\n\n" + guard)
    tick.write_text(body)


def adapt_spinner_dropdown_layout(decoded: Path) -> None:
    """Use the bundled Samsung row geometry on Android framework themes."""
    path = decoded / "res/layout/spinner_dropdown_item.xml"
    text = path.read_text()
    root = ET.fromstring(text)
    android = "{http://schemas.android.com/apk/res/android}"
    expected = {
        android + "textSize": "@dimen/camcorder_description_text_size",
        android + "textColor": "@color/spinner_item_color",
        android + "ellipsize": "marquee",
        android + "id": "@android:id/text1",
        android + "layout_width": "match_parent",
        android + "layout_height": "wrap_content",
        android + "singleLine": "true",
        android + "checkMarkTint": "@color/spinner_item_color",
    }
    original = "?android:spinnerDropDownItemStyle"
    compatible = "@style/Widget.AppCompat.DropDownItem.Spinner"
    attributes = dict(root.attrib)
    style = attributes.pop("style", None)
    if (root.tag != "CheckedTextView" or len(root) != 0
            or attributes != expected or style not in (original, compatible)):
        raise ValueError("Unexpected stock spinner dropdown row")
    styles = ET.parse(decoded / "res/values/styles.xml").getroot()
    target = styles.findall("style[@name='Widget.AppCompat.DropDownItem.Spinner']")
    if len(target) != 1 or target[0].get("parent") != "@style/Base.Widget.AppCompat.DropDownItem.Spinner":
        raise ValueError("Missing bundled spinner dropdown style")
    before = 'style="' + style + '"'
    if text.count(before) != 1:
        raise ValueError("Unexpected spinner dropdown style count")
    if style == original:
        path.write_text(text.replace(before, 'style="' + compatible + '"', 1))


def patch_front_fallback_active_array(decoded):
    """Bound virtual Samsung front coordinates before stock zoom calculations."""
    path = Path(decoded) / "smali/com/samsung/android/camera/core2/CamCapability.smali"
    text = path.read_text()
    signature = "public getSensorInfoActiveArraySize(Ljava/lang/Integer;)Landroid/graphics/Rect;"
    pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                         + r"\n.*?^\.end method$", re.S)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("Expected one stock optional active-array getter")
    match = matches[0]
    body = match[0]
    old = """    :cond_3
    return-object p1"""
    new = """    :cond_3
    invoke-virtual {p0}, Lcom/samsung/android/camera/core2/CamCapability;->getSensorInfoActiveArraySize()Landroid/graphics/Rect;
    move-result-object v1
    iget-object v0, p0, Lcom/samsung/android/camera/core2/CamCapability;->mCameraId:Ljava/lang/String;
    invoke-static {v0, v1, p1}, Lorg/lineageos/camera/compat/CameraDeviceCompat;->constrainFallbackActiveArray(Ljava/lang/String;Landroid/graphics/Rect;Landroid/graphics/Rect;)Landroid/graphics/Rect;
    move-result-object p1
    return-object p1"""
    if body.count("    .locals 1") != 1 or body.count(old) != 1:
        raise ValueError("Unexpected stock optional active-array getter body")
    body = body.replace("    .locals 1", "    .locals 2").replace(old, new)
    path.write_text(text[:match.start()] + body + text[match.end():])


def patch_pro_exposure(decoded):
    capability = (Path(decoded) / "smali_classes2/com/sec/android/app/camera/"
                  "engine/request/CapabilityImpl.smali")
    text = capability.read_text()
    signature = "public getSensorInfoExposureTimeRange()Landroid/util/Range;"
    pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                         + r"\n.*?^\.end method$", re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("Expected one stock Pro exposure range getter")
    match = matches[0]
    body = match[0]
    original = (
        "    iget-object p0, p0, Lcom/sec/android/app/camera/engine/request/"
        "CapabilityImpl;->mCamCapability:Lcom/samsung/android/camera/core2/CamCapability;\n\n"
        "    invoke-virtual {p0}, Lcom/samsung/android/camera/core2/CamCapability;"
        "->getSamsungSensorInfoExposureTimeRange()Landroid/util/Range;\n\n"
        "    move-result-object p0")
    replacement = (
        "    iget-object v0, p0, Lcom/sec/android/app/camera/engine/request/"
        "CapabilityImpl;->mCamCapability:Lcom/samsung/android/camera/core2/CamCapability;\n\n"
        "    invoke-virtual {v0}, Lcom/samsung/android/camera/core2/CamCapability;"
        "->getSamsungSensorInfoExposureTimeRange()Landroid/util/Range;\n\n"
        "    move-result-object v1\n\n"
        "    invoke-virtual {v0}, Lcom/samsung/android/camera/core2/CamCapability;"
        "->getSensorInfoExposureTimeRange()Landroid/util/Range;\n\n"
        "    move-result-object v0\n\n"
        "    invoke-static {v0, v1}, Lorg/lineageos/camera/compat/CameraDeviceCompat;"
        "->constrainExposureTimeRange(Landroid/util/Range;Landroid/util/Range;)"
        "Landroid/util/Range;\n\n"
        "    move-result-object p0")
    if body.count(original) != 1 or body.count("    .locals 0") != 1:
        raise ValueError("Unexpected stock Pro exposure range getter")
    body = body.replace("    .locals 0", "    .locals 2").replace(original, replacement)
    capability.write_text(text[:match.start()] + body + text[match.end():])

    pro = (Path(decoded) / "smali_classes2/com/sec/android/app/camera/"
           "shootingmode/Pro.smali")
    text = pro.read_text()
    signature = "private initShutterSpeedSliderRange()V"
    pattern = re.compile(r"(?m)^\.method " + re.escape(signature)
                         + r"\n.*?^\.end method$", re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("Expected one stock Pro shutter slider initializer")
    match = matches[0]
    body = match[0]
    if ":lineage_lower_shutter_bound" in body or body.count("    .locals 9") != 1:
        raise ValueError("Unexpected stock Pro shutter slider registers")
    lower = (
        "    invoke-direct {p0, v3}, Lcom/sec/android/app/camera/shootingmode/Pro;"
        "->findNearestShutter(I)I\n\n"
        "    move-result v3")
    upper = (
        "    invoke-direct {p0, v4}, Lcom/sec/android/app/camera/shootingmode/Pro;"
        "->findNearestShutter(I)I\n\n"
        "    move-result v4")
    if body.count(lower) != 1 or body.count(upper) != 1:
        raise ValueError("Unexpected stock Pro shutter slider endpoints")
    lower_guard = (
        "\n\n    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;"
        "->hasSamsungStreamOptions()Z\n\n"
        "    move-result v4\n\n"
        "    if-nez v4, :lineage_lower_shutter_done\n\n"
        "    :lineage_lower_shutter_bound\n"
        "    invoke-static {v3}, Lcom/sec/android/app/camera/util/MakerParameter;"
        "->getExposureTime(I)J\n\n"
        "    move-result-wide v5\n\n"
        "    invoke-virtual {v0}, Landroid/util/Range;->getLower()Ljava/lang/Comparable;\n\n"
        "    move-result-object v4\n\n"
        "    check-cast v4, Ljava/lang/Long;\n\n"
        "    invoke-virtual {v4}, Ljava/lang/Long;->longValue()J\n\n"
        "    move-result-wide v7\n\n"
        "    cmp-long v4, v5, v7\n\n"
        "    if-gez v4, :lineage_lower_shutter_done\n\n"
        "    add-int/lit8 v3, v3, 0x1\n\n"
        "    goto :lineage_lower_shutter_bound\n\n"
        "    :lineage_lower_shutter_done\n"
        "    const-wide/16 v5, 0x3e8\n\n"
        "    move v9, v3")
    upper_guard = (
        "\n\n    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;"
        "->hasSamsungStreamOptions()Z\n\n"
        "    move-result v5\n\n"
        "    if-nez v5, :lineage_upper_shutter_done\n\n"
        "    :lineage_upper_shutter_bound\n"
        "    invoke-static {v4}, Lcom/sec/android/app/camera/util/MakerParameter;"
        "->getExposureTime(I)J\n\n"
        "    move-result-wide v7\n\n"
        "    invoke-virtual {v0}, Landroid/util/Range;->getUpper()Ljava/lang/Comparable;\n\n"
        "    move-result-object v5\n\n"
        "    check-cast v5, Ljava/lang/Long;\n\n"
        "    invoke-virtual {v5}, Ljava/lang/Long;->longValue()J\n\n"
        "    move-result-wide v5\n\n"
        "    cmp-long v5, v7, v5\n\n"
        "    if-lez v5, :lineage_upper_shutter_done\n\n"
        "    add-int/lit8 v4, v4, -0x1\n\n"
        "    goto :lineage_upper_shutter_bound\n\n"
        "    :lineage_upper_shutter_done\n"
        "    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;"
        "->hasSamsungStreamOptions()Z\n\n"
        "    move-result v5\n\n"
        "    if-nez v5, :lineage_stored_shutter_done\n\n"
        "    iget-object v5, p0, Lcom/sec/android/app/camera/shootingmode/Pro;"
        "->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;\n\n"
        "    invoke-interface {v5}, Lcom/sec/android/app/camera/interfaces/"
        "CameraSettings;->getShutterSpeed()I\n\n"
        "    move-result v6\n\n"
        "    if-eqz v6, :lineage_stored_shutter_done\n\n"
        "    if-lt v6, v9, :lineage_stored_shutter_lower\n\n"
        "    if-le v6, v4, :lineage_stored_shutter_done\n\n"
        "    move v6, v4\n\n"
        "    goto :lineage_stored_shutter_apply\n\n"
        "    :lineage_stored_shutter_lower\n"
        "    move v6, v9\n\n"
        "    :lineage_stored_shutter_apply\n"
        "    invoke-interface {v5, v6}, Lcom/sec/android/app/camera/interfaces/"
        "CameraSettings;->setShutterSpeed(I)V\n\n"
        "    invoke-direct {p0, v6}, Lcom/sec/android/app/camera/shootingmode/"
        "Pro;->updateShutterSpeedValue(I)V\n\n"
        "    :lineage_stored_shutter_done")
    body = body.replace("    .locals 9", "    .locals 10")
    body = body.replace(lower, lower + lower_guard).replace(upper, upper + upper_guard)
    pro.write_text(text[:match.start()] + body + text[match.end():])


EFFECT_CAPABILITY = "Lorg/lineageos/camera/compat/CameraDeviceCompat;->isSamsungEffectProcessorSupported()Z"
EFFECT_REQUIRE = "Lorg/lineageos/camera/compat/CameraDeviceCompat;->requireSamsungEffectProcessor()V"
PRO_CLASS = "Lcom/sec/android/app/camera/shootingmode/Pro;"
PRO_RESET = """
.method private resetUnsupportedColorTune()V
    .locals 2
    invoke-static {}, Lorg/lineageos/camera/compat/CameraDeviceCompat;->isSamsungEffectProcessorSupported()Z
    move-result v0
    if-nez v0, :lineage_effect_color_ready
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/Pro;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    const/4 v1, 0x0
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setColorTuneType(I)V
    iput v1, p0, Lcom/sec/android/app/camera/shootingmode/Pro;->mLastColorTuneType:I
    :lineage_effect_color_ready
    return-void
.end method
"""


def patch_unavailable_effect_pdk(decoded):
    decoded = Path(decoded)
    effect_path = decoded / "smali/com/samsung/android/camera/effect/SecEffectProcessor.smali"
    pro_path = decoded / "smali_classes2/com/sec/android/app/camera/shootingmode/Pro.smali"
    effect = effect_path.read_text()
    pro = pro_path.read_text()
    if EFFECT_CAPABILITY in effect or EFFECT_REQUIRE in effect or "resetUnsupportedColorTune()V" in pro:
        raise ValueError("Effect PDK safety adaptation already applied")

    def replace_method(text, signature, callback):
        pattern = re.compile(r"(?m)^\.method " + re.escape(signature) + r"\n.*?^\.end method$", re.S)
        found = list(pattern.finditer(text))
        if len(found) != 1:
            raise ValueError("Unexpected stock effect method: " + signature)
        m = found[0]
        return text[:m.start()] + callback(m[0]) + text[m.end():]

    def guard_clinit(body):
        start = '    const-string v0, "camera_effect_processor_jni"'
        if body.count(start) != 1 or body.count('->native_init()V') != 1 or body.count('    return-void') != 1:
            raise ValueError("Unexpected stock effect JNI initializer")
        gate = ("    invoke-static {}, " + EFFECT_CAPABILITY + "\n"
                "    move-result v0\n"
                "    if-eqz v0, :lineage_effect_pdk_unavailable\n\n")
        return body.replace(start, gate + start).replace("    return-void", "    :lineage_effect_pdk_unavailable\n    return-void")

    effect = replace_method(effect, "static constructor <clinit>()V", guard_clinit)
    constructor_count = 0
    def guard_constructor(body):
        nonlocal constructor_count
        call = "    invoke-direct {p0}, Ljava/lang/Object;-><init>()V"
        if body.count(call) != 1 or body.count("->native_setup(Ljava/lang/Object;I)V") != 1:
            raise ValueError("Unexpected stock effect constructor")
        constructor_count += 1
        return body.replace(call, call + "\n\n    invoke-static {}, " + EFFECT_REQUIRE)
    effect = re.sub(r"(?m)^\.method public constructor <init>\([^\n]+\n.*?^\.end method$",
                    lambda m: guard_constructor(m[0]), effect, flags=re.S)
    if constructor_count != 6:
        raise ValueError("Expected six stock effect constructors")

    def insert_reset(body):
        locals_line = re.search(r"(?m)^    \.locals \d+$", body)
        if not locals_line:
            raise ValueError("Missing stock Pro locals")
        call = "\n\n    invoke-direct {p0}, " + PRO_CLASS + "->resetUnsupportedColorTune()V"
        return body[:locals_line.end()] + call + body[locals_line.end():]
    for signature in (
        "public onCreateView(Lcom/samsung/android/glview/GLContext;Lcom/samsung/android/glview/GLViewGroup;Lcom/sec/android/app/camera/interfaces/BaseMenuController;Lcom/sec/android/app/camera/interfaces/MenuManager;)V",
        "public onActivate(Lcom/sec/android/app/camera/interfaces/Engine;)V",
        "public onConnectMakerPrepared(Lcom/sec/android/app/camera/interfaces/Capability;Lcom/sec/android/app/camera/interfaces/Engine$ConnectionInfo;)V",
    ):
        pro = replace_method(pro, signature, insert_reset)

    def guard_color_callback(body):
        locals_line = re.search(r"(?m)^    \.locals ([1-9]\d*)$", body)
        if not locals_line:
            raise ValueError("Missing stock color callback temporary register")
        gate = ("\n\n    invoke-static {}, " + EFFECT_CAPABILITY + "\n"
                "    move-result v0\n"
                "    if-nez v0, :lineage_effect_color_callback\n"
                "    invoke-direct {p0}, " + PRO_CLASS + "->resetUnsupportedColorTune()V\n"
                "    return-void\n"
                "    :lineage_effect_color_callback")
        return body[:locals_line.end()] + gate + body[locals_line.end():]
    for signature in (
        "private changeToColorTuneMode(I)V",
        "private setColorTuneParameter(I)V",
        "private showColorTuneSettingMenu(I)V",
        "private updateColorTuneMode()V",
    ):
        pro = replace_method(pro, signature, guard_color_callback)

    def hide_color_button(body):
        needle = ("    iget-object v0, p0, " + PRO_CLASS + "->mProButtonGroup:Lcom/samsung/android/glview/GLGridList;\n\n"
                  "    iget-object v1, p0, " + PRO_CLASS + "->mColorTuneButton:Lcom/sec/android/app/camera/widget/gl/ProItem;\n\n"
                  "    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLGridList;->addView(Lcom/samsung/android/glview/GLView;)V")
        if body.count(needle) != 1:
            raise ValueError("Unexpected stock Pro color-button attachment")
        guard = ("\n\n    invoke-static {}, " + EFFECT_CAPABILITY + "\n"
                 "    move-result v0\n"
                 "    if-nez v0, :lineage_effect_color_button\n"
                 "    iget-object v0, p0, " + PRO_CLASS + "->mColorTuneButton:Lcom/sec/android/app/camera/widget/gl/ProItem;\n"
                 "    const/4 v1, 0x4\n"
                 "    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setVisibility(I)V\n"
                 "    const/4 v1, 0x1\n"
                 "    invoke-virtual {v0, v1}, Lcom/sec/android/app/camera/widget/gl/ProItem;->setDim(Z)V\n"
                 "    const/4 v1, 0x0\n"
                 "    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setClickable(Z)V\n"
                 "    :lineage_effect_color_button")
        return body.replace(needle, needle + guard)
    pro = replace_method(pro, "private makeProButtonGroup()V", hide_color_button)
    # Both classes are written only after every stock contract has passed.
    effect_path.write_text(effect)
    pro_path.write_text(pro + "\n" + PRO_RESET)


PRO = 'Lcom/sec/android/app/camera/shootingmode/Pro;'
SETTINGS = 'Lcom/sec/android/app/camera/interfaces/CameraSettings;'
KEY = 'Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;'
CONTROLLER = 'Lcom/sec/android/app/camera/engine/AeAfController;'
MAKER = 'Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;'
PARAM = 'Lcom/sec/android/app/camera/util/MakerParameter;'
CAP = 'Lcom/sec/android/app/camera/interfaces/Capability;'
ENGINE = 'Lcom/sec/android/app/camera/interfaces/Engine;'
COMMON = 'Lcom/sec/android/app/camera/engine/CommonEngine;'
PUBLIC = 'Lcom/samsung/android/camera/core2/MakerPublicKey;'


def _iso_method(text, signature):
    pattern = re.compile(r'^\.method ' + re.escape(signature) + r'\n.*?^\.end method$', re.M | re.S)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError('Expected one method: ' + signature)
    return matches[0]


def _iso_replace(text, signature, before, after):
    method = _iso_method(text, signature)
    block = method.group(0)
    if block.count(before) != 1:
        raise ValueError('Unexpected ISO method body: ' + signature)
    block = block.replace(before, after)
    return text[:method.start()] + block + text[method.end():]


def patch_public_pro_iso(decoded):
    """Pair real manual exposure on the current AOSP Exynos9810 HAL."""
    base = Path(decoded) / 'smali_classes2/com/sec/android/app/camera'
    pro_path = base / 'shootingmode/Pro.smali'
    controller_path = base / 'engine/AeAfController.smali'
    pro = pro_path.read_text()
    controller = controller_path.read_text()
    if 'normalizePublicExposureSetting' in pro or 'applyPublicProExposure' in controller:
        raise ValueError('Public Pro ISO adaptation was already applied')

    if pro.count('# direct methods\n') != 1:
        raise ValueError('Unexpected Pro direct-method marker')
    pro = pro.replace('# direct methods\n',
        '.field private mPublicExposureNormalizing:Z\n'
        '.field private mPublicExposureCapability:' + CAP + '\n\n# direct methods\n', 1)
    pro = _iso_replace(pro,
        'public onCameraSettingChanged(' + KEY + 'I)V',
        '    .locals 4\n',
        '    .locals 4\n\n'
        '    invoke-direct {p0, p1, p2}, ' + PRO + '->normalizePublicExposureSetting(' + KEY + 'I)I\n\n'
        '    move-result p2\n')
    pro = _iso_replace(pro,
        'public onStartPreviewPrepared(' + MAKER + CAP + ')V',
        '    .locals 6\n',
        '    .locals 6\n\n'
        '    iput-object p2, p0, ' + PRO + '->mPublicExposureCapability:' + CAP + '\n\n'
        '    invoke-direct {p0}, ' + PRO + '->preparePublicExposureSettings()V\n')

    pro = _iso_replace(pro,
        'public onStartPreviewPrepared(' + MAKER + CAP + ')V',
        '    invoke-static {v2, v3}, ' + PARAM + '->getAeModeByFlashSetting(IZ)I\n\n'
        '    move-result v2\n',
        '    invoke-static {v2, v3}, ' + PARAM + '->getAeModeByFlashSetting(IZ)I\n\n'
        '    move-result v2\n\n'
        '    if-eqz v3, :lineage_initial_ae_done\n'
        '    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z\n'
        '    move-result v3\n'
        '    if-nez v3, :lineage_initial_ae_done\n'
        '    const/4 v2, 0x0\n'
        '    :lineage_initial_ae_done\n')

    methods = '''
.method private clampPublicIsoIndex(I)I
    .locals 5

    if-lez p1, :none
    iget-object v0, p0, @PRO@->mPublicExposureCapability:@CAP@
    if-eqz v0, :none
    invoke-interface {v0}, @CAP@->getSensorInfoSensitivityRange()Landroid/util/Range;
    move-result-object v0
    if-eqz v0, :none
    invoke-virtual {v0}, Landroid/util/Range;->getLower()Ljava/lang/Comparable;
    move-result-object v1
    check-cast v1, Ljava/lang/Integer;
    invoke-virtual {v1}, Ljava/lang/Integer;->intValue()I
    move-result v1
    invoke-virtual {v0}, Landroid/util/Range;->getUpper()Ljava/lang/Comparable;
    move-result-object v2
    check-cast v2, Ljava/lang/Integer;
    invoke-virtual {v2}, Ljava/lang/Integer;->intValue()I
    move-result v2
    const/4 v0, 0x1
    const/16 v3, 0xf
    :lower
    if-gt v0, v3, :none
    invoke-static {v0}, @PARAM@->getSensorSensitivity(I)I
    move-result v4
    if-ge v4, v1, :upper
    add-int/lit8 v0, v0, 0x1
    goto :lower
    :upper
    if-lt v3, v0, :none
    invoke-static {v3}, @PARAM@->getSensorSensitivity(I)I
    move-result v4
    if-le v4, v2, :clamp
    add-int/lit8 v3, v3, -0x1
    goto :upper
    :clamp
    invoke-static {p1, v0}, Ljava/lang/Math;->max(II)I
    move-result p1
    invoke-static {p1, v3}, Ljava/lang/Math;->min(II)I
    move-result p1
    return p1
    :none
    const/4 p1, 0x0
    return p1
.end method

.method private clampPublicShutterIndex(I)I
    .locals 8

    if-lez p1, :none
    iget-object v0, p0, @PRO@->mPublicExposureCapability:@CAP@
    if-eqz v0, :none
    invoke-interface {v0}, @CAP@->getSensorInfoExposureTimeRange()Landroid/util/Range;
    move-result-object v0
    if-eqz v0, :none
    invoke-virtual {v0}, Landroid/util/Range;->getLower()Ljava/lang/Comparable;
    move-result-object v1
    check-cast v1, Ljava/lang/Long;
    invoke-virtual {v1}, Ljava/lang/Long;->longValue()J
    move-result-wide v1
    invoke-virtual {v0}, Landroid/util/Range;->getUpper()Ljava/lang/Comparable;
    move-result-object v3
    check-cast v3, Ljava/lang/Long;
    invoke-virtual {v3}, Ljava/lang/Long;->longValue()J
    move-result-wide v3
    const/4 v0, 0x1
    const/16 v5, 0x24
    :lower
    if-gt v0, v5, :none
    invoke-static {v0}, @PARAM@->getExposureTime(I)J
    move-result-wide v6
    cmp-long v6, v6, v1
    if-gez v6, :upper
    add-int/lit8 v0, v0, 0x1
    goto :lower
    :upper
    if-lt v5, v0, :none
    invoke-static {v5}, @PARAM@->getExposureTime(I)J
    move-result-wide v6
    cmp-long v6, v6, v3
    if-lez v6, :clamp
    add-int/lit8 v5, v5, -0x1
    goto :upper
    :clamp
    invoke-static {p1, v0}, Ljava/lang/Math;->max(II)I
    move-result p1
    invoke-static {p1, v5}, Ljava/lang/Math;->min(II)I
    move-result p1
    return p1
    :none
    const/4 p1, 0x0
    return p1
.end method

.method private preparePublicExposureSettings()V
    .locals 4

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :done
    iget-object v0, p0, @PRO@->mCameraSettings:@SETTINGS@
    invoke-interface {v0}, @SETTINGS@->getIso()I
    move-result v1
    invoke-direct {p0, v1}, @PRO@->clampPublicIsoIndex(I)I
    move-result v1
    invoke-interface {v0}, @SETTINGS@->getShutterSpeed()I
    move-result v2
    invoke-direct {p0, v2}, @PRO@->clampPublicShutterIndex(I)I
    move-result v2
    if-eqz v1, :auto
    if-nez v2, :apply
    :auto
    const/4 v1, 0x0
    const/4 v2, 0x0
    :apply
    const/4 v3, 0x1
    iput-boolean v3, p0, @PRO@->mPublicExposureNormalizing:Z
    :try_start
    invoke-interface {v0, v1}, @SETTINGS@->setIso(I)V
    invoke-interface {v0, v2}, @SETTINGS@->setShutterSpeed(I)V
    :try_end
    const/4 v3, 0x0
    iput-boolean v3, p0, @PRO@->mPublicExposureNormalizing:Z
    :done
    return-void
    :cleanup
    move-exception v0
    const/4 v3, 0x0
    iput-boolean v3, p0, @PRO@->mPublicExposureNormalizing:Z
    throw v0
    .catchall {:try_start .. :try_end} :cleanup
.end method

.method private normalizePublicExposureSetting(@KEY@I)I
    .locals 5

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :unchanged
    iget-boolean v0, p0, @PRO@->mPublicExposureNormalizing:Z
    if-nez v0, :unchanged
    sget-object v1, @KEY@->ISO:@KEY@
    if-eq p1, v1, :eligible
    sget-object v1, @KEY@->SHUTTER_SPEED:@KEY@
    if-ne p1, v1, :unchanged
    :eligible
    iget-object v0, p0, @PRO@->mCameraSettings:@SETTINGS@
    sget-object v1, @KEY@->ISO:@KEY@
    if-ne p1, v1, :current_shutter
    invoke-interface {v0}, @SETTINGS@->getIso()I
    move-result v1
    goto :current_value
    :current_shutter
    invoke-interface {v0}, @SETTINGS@->getShutterSpeed()I
    move-result v1
    :current_value
    if-eq p2, v1, :current_event
    return v1
    :current_event
    const/4 v0, 0x1
    iput-boolean v0, p0, @PRO@->mPublicExposureNormalizing:Z
    :try_start
    iget-object v0, p0, @PRO@->mCameraSettings:@SETTINGS@
    if-lez p2, :auto
    sget-object v1, @KEY@->ISO:@KEY@
    if-ne p1, v1, :shutter
    invoke-direct {p0, p2}, @PRO@->clampPublicIsoIndex(I)I
    move-result p2
    if-eqz p2, :auto
    invoke-interface {v0}, @SETTINGS@->getShutterSpeed()I
    move-result v2
    if-nez v2, :clamp_shutter
    iget v2, p0, @PRO@->mLastNearestShutterSpeed:I
    :clamp_shutter
    invoke-direct {p0, v2}, @PRO@->clampPublicShutterIndex(I)I
    move-result v2
    if-eqz v2, :not_measured
    move v1, p2
    goto :manual
    :shutter
    invoke-direct {p0, p2}, @PRO@->clampPublicShutterIndex(I)I
    move-result p2
    if-eqz p2, :auto
    move v2, p2
    invoke-interface {v0}, @SETTINGS@->getIso()I
    move-result v1
    if-nez v1, :clamp_iso
    iget v1, p0, @PRO@->mLastNearestIso:I
    :clamp_iso
    invoke-direct {p0, v1}, @PRO@->clampPublicIsoIndex(I)I
    move-result v1
    if-eqz v1, :auto
    :manual
    invoke-interface {v0, v1}, @SETTINGS@->setIso(I)V
    const/4 v3, 0x1
    invoke-direct {p0, v3}, @PRO@->setShutterPriorityActivate(Z)V
    invoke-interface {v0, v2}, @SETTINGS@->setShutterSpeed(I)V
    invoke-direct {p0, v2}, @PRO@->updateShutterSpeedValue(I)V
    goto :refresh
    :not_measured
    const-string v3, "Pro"
    const-string v4, "Manual ISO waits for a measured shutter value"
    invoke-static {v3, v4}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I
    :auto
    const/4 p2, 0x0
    invoke-interface {v0, p2}, @SETTINGS@->setIso(I)V
    invoke-interface {v0, p2}, @SETTINGS@->setShutterSpeed(I)V
    invoke-direct {p0, p2}, @PRO@->setShutterPriorityActivate(Z)V
    invoke-direct {p0, p2}, @PRO@->updateShutterSpeedValue(I)V
    :refresh
    iget-object v0, p0, @PRO@->mBaseMenuController:Lcom/sec/android/app/camera/interfaces/BaseMenuController;
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CommandId;->SHOOTING_MODE_PRO:Lcom/sec/android/app/camera/interfaces/CommandId;
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/BaseMenuController;->refreshQuickSetting(Lcom/sec/android/app/camera/interfaces/CommandId;)V
    :try_end
    const/4 v0, 0x0
    iput-boolean v0, p0, @PRO@->mPublicExposureNormalizing:Z
    :unchanged
    return p2
    :cleanup
    move-exception v1
    const/4 v0, 0x0
    iput-boolean v0, p0, @PRO@->mPublicExposureNormalizing:Z
    throw v1
    .catchall {:try_start .. :try_end} :cleanup
.end method
'''
    for name, value in [('PRO', PRO), ('SETTINGS', SETTINGS), ('KEY', KEY),
                        ('PARAM', PARAM), ('ENGINE', ENGINE), ('CAP', CAP)]:
        methods = methods.replace('@' + name + '@', value)
    # Stock uses mBaseMenuController? Fail fast rather than introducing a missing field.
    if '.field private mBaseMenuController:' not in pro:
        # The existing synthetic getter returns the controller from mCameraContext.
        methods = methods.replace(
            '    iget-object v0, p0, ' + PRO + '->mBaseMenuController:Lcom/sec/android/app/camera/interfaces/BaseMenuController;',
            '    iget-object v0, p0, ' + PRO + '->mCameraContext:Lcom/sec/android/app/camera/interfaces/CameraContext;\n'
            '    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraContext;->getBaseMenuController()Lcom/sec/android/app/camera/interfaces/BaseMenuController;\n'
            '    move-result-object v0')
    pro += methods

    controller = _iso_replace(controller, 'setSensorSensitivity(I)V',
        '    .locals 2\n',
        '    .locals 2\n\n'
        '    invoke-direct {p0}, ' + CONTROLLER + '->isPublicProExposure()Z\n'
        '    move-result v0\n'
        '    if-eqz v0, :lineage_stock_iso\n'
        '    iget-object v0, p0, ' + CONTROLLER + '->mCameraSettings:' + SETTINGS + '\n'
        '    invoke-interface {v0}, ' + SETTINGS + '->getShutterSpeed()I\n'
        '    move-result v0\n'
        '    invoke-virtual {p0, v0}, ' + CONTROLLER + '->setSensorExposureTime(I)V\n'
        '    return-void\n'
        '    :lineage_stock_iso\n')
    controller = _iso_replace(controller,
        'public synthetic lambda$setSensorExposureTime$16$AeAfController(I' + MAKER + ')Z',
        '    .locals 7\n',
        '    .locals 7\n\n'
        '    invoke-direct {p0}, ' + CONTROLLER + '->isPublicProExposure()Z\n'
        '    move-result v2\n'
        '    if-eqz v2, :lineage_stock_exposure\n'
        '    invoke-direct {p0, p2}, ' + CONTROLLER + '->applyPublicProExposure(' + MAKER + ')Z\n'
        '    move-result v2\n'
        '    return v2\n'
        '    :lineage_stock_exposure\n')
    methods = '''
.method private isPublicProExposure()Z
    .locals 2

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :no
    iget-object v0, p0, @CONTROLLER@->mCameraSettings:@SETTINGS@
    invoke-interface {v0}, @SETTINGS@->getModeCustomSetting()I
    move-result v0
    const/4 v1, 0x3
    if-ne v0, v1, :no
    iget-object v0, p0, @CONTROLLER@->mCameraSettings:@SETTINGS@
    invoke-interface {v0}, @SETTINGS@->getCameraFacing()I
    move-result v0
    const/4 v1, 0x1
    if-ne v0, v1, :no
    const/4 v0, 0x1
    return v0
    :no
    const/4 v0, 0x0
    return v0
.end method

.method private applyPublicProExposure(@MAKER@)Z
    .locals 8

    iget-object v0, p0, @CONTROLLER@->mCameraSettings:@SETTINGS@
    invoke-interface {v0}, @SETTINGS@->getIso()I
    move-result v1
    invoke-interface {v0}, @SETTINGS@->getShutterSpeed()I
    move-result v2
    if-lez v1, :auto
    if-lez v2, :auto
    invoke-static {v1}, @PARAM@->getSensorSensitivity(I)I
    move-result v1
    invoke-static {v2}, @PARAM@->getExposureTime(I)J
    move-result-wide v4
    iget-object v2, p0, @CONTROLLER@->mEngine:@COMMON@
    invoke-virtual {v2}, @COMMON@->getCapability()@CAP@
    move-result-object v2
    invoke-interface {v2}, @CAP@->getSensorInfoSensitivityRange()Landroid/util/Range;
    move-result-object v3
    if-eqz v3, :auto
    invoke-static {v1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v1
    invoke-virtual {v3, v1}, Landroid/util/Range;->clamp(Ljava/lang/Comparable;)Ljava/lang/Comparable;
    move-result-object v1
    check-cast v1, Ljava/lang/Integer;
    invoke-interface {v2}, @CAP@->getSensorInfoExposureTimeRange()Landroid/util/Range;
    move-result-object v3
    if-eqz v3, :auto
    invoke-static {v4, v5}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v2
    invoke-virtual {v3, v2}, Landroid/util/Range;->clamp(Ljava/lang/Comparable;)Ljava/lang/Comparable;
    move-result-object v2
    check-cast v2, Ljava/lang/Long;
    const/4 v0, 0x0
    invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v0
    goto :compare
    :auto
    iget-object v0, p0, @CONTROLLER@->mCameraSettings:@SETTINGS@
    invoke-interface {v0}, @SETTINGS@->getFlash()I
    move-result v0
    const/4 v1, 0x0
    invoke-static {v0, v1}, @PARAM@->getAeModeByFlashSetting(IZ)I
    move-result v0
    invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v0
    const/4 v1, 0x0
    invoke-static {v1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v1
    const-wide/16 v4, 0x0
    invoke-static {v4, v5}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v2
    :compare
    sget-object v3, @PUBLIC@->REQUEST_CONTROL_AE_MODE:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p1, v3, v0}, @MAKER@->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :apply
    sget-object v3, @PUBLIC@->REQUEST_SENSOR_SENSITIVITY:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p1, v3, v1}, @MAKER@->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :apply
    sget-object v3, @PUBLIC@->REQUEST_SENSOR_EXPOSURE_TIME:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p1, v3, v2}, @MAKER@->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :apply
    const/4 v3, 0x0
    return v3
    :apply
    sget-object v3, @PUBLIC@->REQUEST_CONTROL_AE_MODE:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p1, v3, v0}, @MAKER@->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    sget-object v3, @PUBLIC@->REQUEST_SENSOR_SENSITIVITY:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p1, v3, v1}, @MAKER@->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    sget-object v3, @PUBLIC@->REQUEST_SENSOR_EXPOSURE_TIME:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p1, v3, v2}, @MAKER@->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    const/4 v3, 0x1
    return v3
.end method
'''
    for name, value in [('CONTROLLER', CONTROLLER), ('SETTINGS', SETTINGS),
                        ('MAKER', MAKER), ('PARAM', PARAM), ('CAP', CAP),
                        ('COMMON', COMMON), ('PUBLIC', PUBLIC)]:
        methods = methods.replace('@' + name + '@', value)
    controller += methods
    pro_path.write_text(pro)
    controller_path.write_text(controller)
    return [pro_path, controller_path]


PRO_ISO_CLASS = "Lcom/sec/android/app/camera/shootingmode/Pro;"
PRO_ISO_CAP_IMPL = "Lcom/sec/android/app/camera/engine/request/CapabilityImpl;"
PRO_ISO_CAM_CAP = "Lcom/samsung/android/camera/core2/CamCapability;"
PRO_ISO_HELPER = "Lorg/lineageos/camera/compat/ProIsoCompat;"
PRO_ISO_OPTIONS = "Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z"


def _r17_method(text, signature):
    found = list(re.finditer(r"(?m)^\.method " + re.escape(signature)
                            + r"\n.*?^\.end method$", text, re.S))
    if len(found) != 1:
        raise ValueError("Unexpected Pro ISO method: " + signature)
    return found[0]


def _r17_replace(text, signature, before, after):
    method = _r17_method(text, signature)
    body = method[0]
    if body.count(before) != 1:
        raise ValueError("Unexpected Pro ISO body: " + signature)
    return text[:method.start()] + body.replace(before, after) + text[method.end():]


PUBLIC_CAP_METHOD = """
.method public getPublicSensorInfoSensitivityRange()Landroid/util/Range;
    .locals 1

    iget-object v0, p0, Lcom/samsung/android/camera/core2/CamCapability;->mCameraCharacteristics:Landroid/hardware/camera2/CameraCharacteristics;
    invoke-static {v0}, Lorg/lineageos/camera/compat/ProIsoCompat;->publicSensitivityRange(Landroid/hardware/camera2/CameraCharacteristics;)Landroid/util/Range;
    move-result-object v0
    return-object v0
.end method
"""

PUBLIC_SLIDER_METHOD = """
.method private initPublicIsoSliderRange(Landroid/util/Range;)Z
    .locals 4

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :stock
    invoke-static {p1}, Lorg/lineageos/camera/compat/ProIsoCompat;->indexBounds(Landroid/util/Range;)[I
    move-result-object v0
    if-eqz v0, :unavailable
    const/4 v1, 0x0
    aget v1, v0, v1
    const/4 v2, 0x1
    aget v2, v0, v2
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->ISO:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    invoke-static {v0, v1}, Lcom/sec/android/app/camera/command/CommandIdMap;->getCommandId(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)Lcom/sec/android/app/camera/interfaces/CommandId;
    move-result-object v1
    invoke-static {v0, v2}, Lcom/sec/android/app/camera/command/CommandIdMap;->getCommandId(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)Lcom/sec/android/app/camera/interfaces/CommandId;
    move-result-object v2
    new-instance v0, Landroid/util/Range;
    invoke-direct {v0, v1, v2}, Landroid/util/Range;-><init>(Ljava/lang/Comparable;Ljava/lang/Comparable;)V
    iget-object v1, p0, Lcom/sec/android/app/camera/shootingmode/Pro;->mIsoSlider:Lcom/sec/android/app/camera/widget/gl/ProSlider;
    invoke-virtual {v1, v0}, Lcom/sec/android/app/camera/widget/gl/ProSlider;->setRange(Landroid/util/Range;)V
    goto :handled
    :unavailable
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/Pro;->mIsoButton:Lcom/sec/android/app/camera/widget/gl/ProItem;
    const/4 v1, 0x1
    invoke-virtual {v0, v1}, Lcom/sec/android/app/camera/widget/gl/ProItem;->setDim(Z)V
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setClickable(Z)V
    const-string v0, "Exynos9810StockCamera"
    const-string v1, "Manual ISO unavailable: no public sensitivity step"
    invoke-static {v0, v1}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I
    :handled
    const/4 v0, 0x1
    return v0
    :stock
    const/4 v0, 0x0
    return v0
.end method
"""


def patch_public_pro_iso_range(decoded):
    """Extend public ISO steps with matching UI and runtime bounds."""
    decoded = Path(decoded)
    relative = [
        "smali/com/samsung/android/camera/core2/CamCapability.smali",
        "smali_classes2/com/sec/android/app/camera/engine/request/CapabilityImpl.smali",
        "smali_classes2/com/sec/android/app/camera/util/MakerParameter.smali",
        "smali_classes2/com/sec/android/app/camera/shootingmode/Pro.smali",
        "smali_classes2/com/sec/android/app/camera/widget/gl/ProSlider.smali",
        "smali_classes2/com/sec/android/app/camera/widget/gl/ProSlider$LabelGroup.smali",
        "smali_classes2/com/sec/android/app/camera/widget/gl/ProWheelListGroup.smali",
        "smali_classes2/com/sec/android/app/camera/widget/gl/ProWheelListGroup$1.smali",
        "smali/com/samsung/android/glview/GLContext.smali",
    ]
    original = {rel: (decoded / rel).read_text() for rel in relative}
    if any(PRO_ISO_HELPER in text or "initPublicIsoSliderRange" in text
           for text in original.values()):
        raise ValueError("Public Pro ISO range adaptation already applied")
    updated = dict(original)
    cam, capability, parameter, pro, slider, labels, wheel, wheel_listener, gl_context = relative
    if original[cam].count(".field private final mCameraCharacteristics:Landroid/hardware/camera2/CameraCharacteristics;") != 1:
        raise ValueError("Unexpected stock camera characteristics field")
    updated[cam] += PUBLIC_CAP_METHOD
    updated[capability] = _r17_replace(
        updated[capability], "public getSensorInfoSensitivityRange()Landroid/util/Range;",
        "    .locals 0\n",
        "    .locals 1\n\n"
        "    invoke-static {}, " + PRO_ISO_OPTIONS + "\n"
        "    move-result v0\n"
        "    if-nez v0, :lineage_stock_iso_range\n"
        "    iget-object v0, p0, " + PRO_ISO_CAP_IMPL + "->mCamCapability:" + PRO_ISO_CAM_CAP + "\n"
        "    invoke-virtual {v0}, " + PRO_ISO_CAM_CAP + "->getPublicSensorInfoSensitivityRange()Landroid/util/Range;\n"
        "    move-result-object v0\n"
        "    return-object v0\n"
        "    :lineage_stock_iso_range\n")
    array_method = _r17_method(original[parameter], "static constructor <clinit>()V")[0]
    values = re.search(r":array_1\s+\.array-data 4\s+(.*?)\s+\.end array-data", array_method, re.S)
    expected = [0, 50, 64, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1600, 3200]
    if values is None or [int(v.strip(), 16) for v in values[1].splitlines()] != expected:
        raise ValueError("Unexpected stock sensor sensitivity table")
    updated[parameter] = _r17_replace(
        updated[parameter], "public static getSensorSensitivity(I)I",
        "    aget p0, v0, p0\n",
        "    aget v0, v0, p0\n\n"
        "    invoke-static {p0, v0}, " + PRO_ISO_HELPER + "->sensorSensitivity(II)I\n"
        "    move-result p0\n")
    for signature, registers in [
        ("private getIsoString(I)Ljava/lang/String;", "p0, v0"),
        ("private updateISOValue(I)V", "v0, v1"),
    ]:
        updated[pro] = _r17_replace(
            updated[pro], signature,
            "    invoke-virtual {" + registers + "}, Landroid/content/res/Resources;->getStringArray(I)[Ljava/lang/String;",
            "    invoke-static {" + registers + "}, " + PRO_ISO_HELPER + "->isoLabels(Landroid/content/res/Resources;I)[Ljava/lang/String;")
    updated[pro] = _r17_replace(
        updated[pro], "private initIsoSliderRange()V",
        '    const-string v1, "Pro"\n',
        "    invoke-direct {p0, v0}, " + PRO_ISO_CLASS + "->initPublicIsoSliderRange(Landroid/util/Range;)Z\n"
        "    move-result v1\n"
        "    if-eqz v1, :lineage_stock_iso_slider\n"
        "    return-void\n"
        "    :lineage_stock_iso_slider\n\n"
        '    const-string v1, "Pro"\n')
    updated[pro] += PUBLIC_SLIDER_METHOD
    title_methods = [
        (slider, "public constructor <init>(Lcom/sec/android/app/camera/interfaces/CameraContext;FFFFILcom/sec/android/app/camera/interfaces/CommandId;)V"),
        (slider, "public show(ILcom/sec/android/app/camera/widget/gl/ProSlider$SliderAnimationType;)V"),
        (labels, "public constructor <init>(Lcom/sec/android/app/camera/widget/gl/ProSlider;Lcom/samsung/android/glview/GLContext;FFFF[ILcom/sec/android/app/camera/interfaces/CommandId;)V"),
        (wheel, "public setCurrentValue(I)V"),
        (wheel_listener, "public onScrollAnimationFinished()V"),
    ]
    for rel, signature in title_methods:
        method = _r17_method(updated[rel], signature)
        pattern = re.compile(r"invoke-virtual (\{[^\n]+\}), L(?:android/content/Context|androidx/appcompat/app/AppCompatActivity);->getString\(I\)Ljava/lang/String;")
        text, count = pattern.subn(lambda m: "invoke-static " + m[1] + ", " + PRO_ISO_HELPER + "->isoTitle(Landroid/content/Context;I)Ljava/lang/String;", method[0])
        if count != 1:
            raise ValueError("Unexpected stock Pro ISO title call count: " + signature + "=" + str(count))
        updated[rel] = updated[rel][:method.start()] + text + updated[rel][method.end():]
    updated[gl_context] = _r17_replace(
        updated[gl_context], "public static getString(I)Ljava/lang/String;",
        "    invoke-virtual {v1, p0}, Landroid/content/res/Resources;->getString(I)Ljava/lang/String;",
        "    invoke-static {v1, p0}, " + PRO_ISO_HELPER + "->isoResourceString(Landroid/content/res/Resources;I)Ljava/lang/String;")
    # Commit all class outputs only after every source contract passes.
    for rel in relative:
        (decoded / rel).write_text(updated[rel])
    return [decoded / rel for rel in relative]

PUBLIC_FPS_METHOD = r'''
.method private applyPublicRecordingFps(Lcom/samsung/android/camera/core2/container/DeviceConfiguration$Parameters;)V
    .locals 5

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :public_fps_done

    invoke-virtual {p1}, Lcom/samsung/android/camera/core2/container/DeviceConfiguration$Parameters;->getMaxFps()Ljava/lang/Integer;
    move-result-object v0
    if-eqz v0, :public_fps_done
    invoke-virtual {v0}, Ljava/lang/Integer;->intValue()I
    move-result v1
    const/16 v2, 0x3c
    if-ne v1, v2, :public_fps_done

    iget-object v3, p0, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->mCamDevice:Lcom/samsung/android/camera/core2/CamDevice;
    invoke-virtual {v3}, Lcom/samsung/android/camera/core2/CamDevice;->getId()Ljava/lang/String;
    move-result-object v3
    const-string v4, "0"
    invoke-virtual {v4, v3}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v4
    if-eqz v4, :public_fps_done

    new-instance v1, Landroid/util/Range;
    invoke-direct {v1, v0, v0}, Landroid/util/Range;-><init>(Ljava/lang/Comparable;Ljava/lang/Comparable;)V
    sget-object v2, Landroid/hardware/camera2/CaptureRequest;->CONTROL_AE_TARGET_FPS_RANGE:Landroid/hardware/camera2/CaptureRequest$Key;
    iget-object v3, p0, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->mCamDevice:Lcom/samsung/android/camera/core2/CamDevice;
    invoke-virtual {v3}, Lcom/samsung/android/camera/core2/CamDevice;->getId()Ljava/lang/String;
    move-result-object v3

    iget-object v4, p0, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->mPreviewRequestBuilderMap:Ljava/util/Map;
    invoke-static {v4, v3, v2, v1}, Lcom/samsung/android/camera/core2/local/vendorkey/SemCaptureRequest;->set(Ljava/util/Map;Ljava/lang/String;Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    iget-object v4, p0, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->mPictureRequestBuilderMap:Ljava/util/Map;
    invoke-static {v4, v3, v2, v1}, Lcom/samsung/android/camera/core2/local/vendorkey/SemCaptureRequest;->set(Ljava/util/Map;Ljava/lang/String;Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    iget-object v4, p0, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->mRecordRequestBuilderMap:Ljava/util/Map;
    invoke-static {v4, v3, v2, v1}, Lcom/samsung/android/camera/core2/local/vendorkey/SemCaptureRequest;->set(Ljava/util/Map;Ljava/lang/String;Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V

    iget-object v0, p0, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->VIDEO_BASE_TAG:Lcom/samsung/android/camera/core2/util/CLog$Tag;
    const-string v1, "applyPublicRecordingFps - public rear recording request [60, 60]"
    invoke-static {v0, v1}, Lcom/samsung/android/camera/core2/util/CLog;->i(Lcom/samsung/android/camera/core2/util/CLog$Tag;Ljava/lang/String;)V

    :public_fps_done
    return-void
.end method
'''


def patch_public_video_requests(decoded):
    root = Path(decoded) / 'smali/com/samsung/android/camera/core2'
    path = root / 'local/vendorkey/SemCameraCharacteristics.smali'
    text = path.read_text()
    pattern = r'(?ms)(^\.method public static getAvailableSessionKeys\(Landroid/hardware/camera2/CameraCharacteristics;\)Ljava/util/List;\n.*?^\.end method\n)'
    matches = re.findall(pattern, text)
    if len(matches) != 1:
        raise ValueError('Expected one stock Samsung session-key getter')
    method = matches[0]
    old = '    move-result-object p0\n\n    return-object p0\n'
    new = '''    move-result-object v0

    if-nez v0, :public_session_keys_return

    invoke-virtual {p0}, Landroid/hardware/camera2/CameraCharacteristics;->getAvailableSessionKeys()Ljava/util/List;
    move-result-object v0

    :public_session_keys_return
    return-object v0
'''
    if method.count(old) != 1:
        raise ValueError('Expected unmodified Samsung session-key getter return')
    path.write_text(text.replace(method, method.replace(old, new), 1))

    path = root / 'maker/VideoMakerBase.smali'
    text = path.read_text()
    marker = '    invoke-virtual {v1, v9, v10}, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->setSessionKeys(Ljava/util/List;Ljava/util/Map;)V\n'
    insertion = '''
    invoke-virtual/range {p2 .. p2}, Lcom/samsung/android/camera/core2/container/DeviceConfiguration;->getParameters()Lcom/samsung/android/camera/core2/container/DeviceConfiguration$Parameters;
    move-result-object v10
    invoke-direct {v1, v10}, Lcom/samsung/android/camera/core2/maker/VideoMakerBase;->applyPublicRecordingFps(Lcom/samsung/android/camera/core2/container/DeviceConfiguration$Parameters;)V
'''
    if text.count(marker) != 1 or 'applyPublicRecordingFps' in text:
        raise ValueError('Expected unmodified video session-key application')
    text = text.replace(marker, marker + insertion, 1)
    path.write_text(text + '\n' + PUBLIC_FPS_METHOD)


PRO_VIDEO_CLASS = 'Lcom/sec/android/app/camera/shootingmode/ProVideo;'
PRO_VIDEO_CONTROLLER = 'Lcom/sec/android/app/camera/engine/AeAfController;'
PRO_VIDEO_KEY = 'Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;'
PRO_VIDEO_ISO_HELPER = 'Lorg/lineageos/camera/compat/ProIsoCompat;'
PRO_VIDEO_OPTIONS = 'Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z'
PRO_VIDEO_EFFECT_CAP = 'Lorg/lineageos/camera/compat/CameraDeviceCompat;->isSamsungEffectProcessorSupported()Z'


def _pro_video_method(text, signature):
    found = list(re.finditer(r'(?m)^\.method ' + re.escape(signature) + r'\n.*?^\.end method$', text, re.S))
    if len(found) != 1:
        raise ValueError('Unexpected ProVideo method: ' + signature)
    return found[0]


def _pro_video_replace(text, signature, before, after):
    m = _pro_video_method(text, signature)
    if m[0].count(before) != 1:
        raise ValueError('Unexpected ProVideo source contract: ' + signature)
    return text[:m.start()] + m[0].replace(before, after) + text[m.end():]


def _pro_video_prepend(text, signature, instructions):
    m = _pro_video_method(text, signature)
    body, count = re.subn(r'(    \.locals \d+\n)', lambda match: match[0] + '\n' + instructions + '\n', m[0], count=1)
    if count != 1:
        raise ValueError('Unexpected ProVideo locals: ' + signature)
    return text[:m.start()] + body + text[m.end():]


def patch_public_pro_video(decoded):
    """Adapt rear ProVideo controls to the public Camera2 recording path."""
    decoded = Path(decoded)
    relative = ['smali_classes2/com/sec/android/app/camera/shootingmode/ProVideo.smali',
                'smali_classes2/com/sec/android/app/camera/engine/AeAfController.smali']
    original = [(decoded / rel).read_text() for rel in relative]
    video, controller = original
    if 'mPublicExposureNormalizing' in video or 'applyPublicProVideoExposure' in controller:
        raise ValueError('Public ProVideo adaptation already applied')
    field = '.field private mVideoColorTune:I'
    if video.count(field) != 1:
        raise ValueError('Unexpected ProVideo colour state field')
    video = video.replace(field, field + '\n\n.field private mPublicExposureNormalizing:Z\n\n.field private mPublicExposureCapability:Lcom/sec/android/app/camera/interfaces/Capability;')
    for signature, registers in [('private getIsoString(I)Ljava/lang/String;', 'p0, v0'),
                                 ('private updateISOValue(I)V', 'v0, v1')]:
        video = _pro_video_replace(video, signature,
            '    invoke-virtual {' + registers + '}, Landroid/content/res/Resources;->getStringArray(I)[Ljava/lang/String;',
            '    invoke-static {' + registers + '}, ' + PRO_VIDEO_ISO_HELPER + '->isoLabels(Landroid/content/res/Resources;I)[Ljava/lang/String;')
    video = _pro_video_replace(video, 'private initIsoSliderRange()V',
        '    const-string v1, "ProVideo"\n',
        '    invoke-direct {p0, v0}, ' + PRO_VIDEO_CLASS + '->initPublicIsoSliderRange(Landroid/util/Range;)Z\n'
        '    move-result v1\n    if-eqz v1, :lineage_video_stock_iso\n    return-void\n    :lineage_video_stock_iso\n\n    const-string v1, "ProVideo"\n')
    video = _pro_video_replace(video, 'private initShutterSpeedSliderRange()V',
        '    const-string v1, "ProVideo"\n',
        '    invoke-direct {p0}, ' + PRO_VIDEO_CLASS + '->initPublicVideoShutterRange()Z\n'
        '    move-result v1\n    if-eqz v1, :lineage_video_stock_shutter\n    return-void\n    :lineage_video_stock_shutter\n\n    const-string v1, "ProVideo"\n')
    video = _pro_video_prepend(video, 'public onCameraSettingChanged(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)V',
        '    invoke-direct {p0, p1, p2}, ' + PRO_VIDEO_CLASS + '->normalizePublicVideoSetting(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)I\n    move-result p2')
    initial = 'public onStartPreviewPrepared(Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;Lcom/sec/android/app/camera/interfaces/Capability;)V'
    video = _pro_video_prepend(video, initial,
        '    iput-object p2, p0, ' + PRO_VIDEO_CLASS + '->mPublicExposureCapability:Lcom/sec/android/app/camera/interfaces/Capability;\n'
        '    invoke-direct {p0}, ' + PRO_VIDEO_CLASS + '->preparePublicExposureSettings()V')
    m = _pro_video_method(video, initial)
    anchor = '    sget-object v0, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_SENSITIVITY:Landroid/hardware/camera2/CaptureRequest$Key;'
    assert m[0].count(anchor) == 1
    after_iso = '    invoke-interface {p1, v0, v1}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V'
    at = m[0].index(after_iso, m[0].index(anchor)) + len(after_iso)
    injection = ('\n\n    invoke-static {}, ' + PRO_VIDEO_OPTIONS + '\n    move-result v0\n'
        '    if-nez v0, :lineage_video_stock_initial\n    iget-object v0, p0, ' + PRO_VIDEO_CLASS + '->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;\n'
        '    invoke-static {v0, p2, p1}, ' + PRO_VIDEO_CONTROLLER + '->applyPublicProVideoExposureSettings(Lcom/sec/android/app/camera/interfaces/CameraSettings;Lcom/sec/android/app/camera/interfaces/Capability;Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z\n'
        '    :lineage_video_stock_initial')
    body = m[0][:at] + injection + m[0][at:]
    video = video[:m.start()] + body + video[m.end():]
    for signature in ['public onCreateView(Lcom/samsung/android/glview/GLContext;Lcom/samsung/android/glview/GLViewGroup;Lcom/sec/android/app/camera/interfaces/BaseMenuController;Lcom/sec/android/app/camera/interfaces/MenuManager;)V',
                      'public onActivate(Lcom/sec/android/app/camera/interfaces/Engine;)V',
                      'public onConnectMakerPrepared(Lcom/sec/android/app/camera/interfaces/Capability;Lcom/sec/android/app/camera/interfaces/Engine$ConnectionInfo;)V']:
        video = _pro_video_prepend(video, signature, '    invoke-direct/range {p0 .. p0}, ' + PRO_VIDEO_CLASS + '->resetUnsupportedVideoColorTune()V')
    for signature in ['private changeToColorTuneMode(I)V', 'private setColorTuneParameter(I)V', 'private updateColorTuneMode()V']:
        video = _pro_video_prepend(video, signature,
            '    invoke-static {}, ' + PRO_VIDEO_EFFECT_CAP + '\n    move-result v0\n    if-nez v0, :lineage_video_colour_supported\n'
            '    invoke-direct {p0}, ' + PRO_VIDEO_CLASS + '->resetUnsupportedVideoColorTune()V\n    return-void\n    :lineage_video_colour_supported')
    video = _pro_video_prepend(video, 'private isColorTuneDimRequired()Z',
        '    invoke-static {}, ' + PRO_VIDEO_EFFECT_CAP + '\n    move-result v0\n    if-nez v0, :lineage_video_colour_dim_stock\n'
        '    const/4 v0, 0x1\n    return v0\n    :lineage_video_colour_dim_stock')
    needle = ('    iget-object v0, p0, ' + PRO_VIDEO_CLASS + '->mProButtonGroup:Lcom/samsung/android/glview/GLGridList;\n\n'
              '    iget-object v1, p0, ' + PRO_VIDEO_CLASS + '->mColorTuneButton:Lcom/sec/android/app/camera/widget/gl/ProItem;\n\n'
              '    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLGridList;->addView(Lcom/samsung/android/glview/GLView;)V')
    hide = ('\n\n    invoke-static {}, ' + PRO_VIDEO_EFFECT_CAP + '\n    move-result v0\n    if-nez v0, :lineage_video_colour_button\n'
            '    iget-object v0, p0, ' + PRO_VIDEO_CLASS + '->mColorTuneButton:Lcom/sec/android/app/camera/widget/gl/ProItem;\n'
            '    const/4 v1, 0x4\n    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setVisibility(I)V\n'
            '    const/4 v1, 0x1\n    invoke-virtual {v0, v1}, Lcom/sec/android/app/camera/widget/gl/ProItem;->setDim(Z)V\n'
            '    const/4 v1, 0x0\n    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setClickable(Z)V\n    :lineage_video_colour_button')
    video = _pro_video_replace(video, 'private makeProButtonGroup()V', needle, needle + hide)
    video += '\n\n' + PRO_VIDEO_EXPOSURE_HELPERS + '\n\n' + PRO_VIDEO_EXTRA_HELPERS
    controller = _pro_video_replace(controller, 'private isPublicProExposure()Z',
        '    const/4 v1, 0x3\n    if-ne v0, v1, :no\n',
        '    const/4 v1, 0x3\n    if-eq v0, v1, :lineage_public_pro_mode\n'
        '    const/16 v1, 0x24\n    if-ne v0, v1, :no\n    :lineage_public_pro_mode\n')
    dispatch = ('    iget-object v0, p0, ' + PRO_VIDEO_CONTROLLER + '->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;\n'
        '    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getModeCustomSetting()I\n    move-result v0\n'
        '    const/16 v1, 0x24\n    if-ne v0, v1, :lineage_video_worker_stock\n'
        '    invoke-virtual {p0, p1}, ' + PRO_VIDEO_CONTROLLER + '->applyPublicProVideoExposure(Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z\n'
        '    move-result v0\n    return v0\n    :lineage_video_worker_stock')
    controller = _pro_video_prepend(controller, 'private applyPublicProExposure(Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z', dispatch)
    torch_dispatch = ('    invoke-direct {p0}, ' + PRO_VIDEO_CONTROLLER + '->isPublicProExposure()Z\n    move-result v0\n    if-eqz v0, :lineage_video_torch_stock\n'
        '    iget-object v0, p0, ' + PRO_VIDEO_CONTROLLER + '->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;\n'
        '    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getModeCustomSetting()I\n    move-result v0\n'
        '    const/16 v1, 0x24\n    if-ne v0, v1, :lineage_video_torch_stock\n'
        '    invoke-virtual {p0, p2}, ' + PRO_VIDEO_CONTROLLER + '->applyPublicProVideoExposure(Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z\n'
        '    move-result v0\n    return v0\n    :lineage_video_torch_stock')
    controller = _pro_video_prepend(controller, 'public synthetic lambda$setTorchFlashMode$18$AeAfController(ILcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z', torch_dispatch)
    controller += '\n\n' + PRO_VIDEO_WORKER
    # Never leave one class updated when another exact stock contract fails.
    for rel, text in zip(relative, [video, controller]):
        (decoded / rel).write_text(text)
    return [decoded / rel for rel in relative]


PRO_VIDEO_EXPOSURE_HELPERS = r"""
.method private clampPublicIsoIndex(I)I
    .locals 5

    if-lez p1, :none
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureCapability:Lcom/sec/android/app/camera/interfaces/Capability;
    if-eqz v0, :none
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/Capability;->getSensorInfoSensitivityRange()Landroid/util/Range;
    move-result-object v0
    if-eqz v0, :none
    invoke-virtual {v0}, Landroid/util/Range;->getLower()Ljava/lang/Comparable;
    move-result-object v1
    check-cast v1, Ljava/lang/Integer;
    invoke-virtual {v1}, Ljava/lang/Integer;->intValue()I
    move-result v1
    invoke-virtual {v0}, Landroid/util/Range;->getUpper()Ljava/lang/Comparable;
    move-result-object v2
    check-cast v2, Ljava/lang/Integer;
    invoke-virtual {v2}, Ljava/lang/Integer;->intValue()I
    move-result v2
    const/4 v0, 0x1
    const/16 v3, 0xf
    :lower
    if-gt v0, v3, :none
    invoke-static {v0}, Lcom/sec/android/app/camera/util/MakerParameter;->getSensorSensitivity(I)I
    move-result v4
    if-ge v4, v1, :upper
    add-int/lit8 v0, v0, 0x1
    goto :lower
    :upper
    if-lt v3, v0, :none
    invoke-static {v3}, Lcom/sec/android/app/camera/util/MakerParameter;->getSensorSensitivity(I)I
    move-result v4
    if-le v4, v2, :clamp
    add-int/lit8 v3, v3, -0x1
    goto :upper
    :clamp
    invoke-static {p1, v0}, Ljava/lang/Math;->max(II)I
    move-result p1
    invoke-static {p1, v3}, Ljava/lang/Math;->min(II)I
    move-result p1
    return p1
    :none
    const/4 p1, 0x0
    return p1
.end method

.method private clampPublicShutterIndex(I)I
    .locals 8

    if-lez p1, :none
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureCapability:Lcom/sec/android/app/camera/interfaces/Capability;
    if-eqz v0, :none
    invoke-direct {p0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->getPublicVideoExposureRange()Landroid/util/Range;
    move-result-object v0
    if-eqz v0, :none
    invoke-virtual {v0}, Landroid/util/Range;->getLower()Ljava/lang/Comparable;
    move-result-object v1
    check-cast v1, Ljava/lang/Long;
    invoke-virtual {v1}, Ljava/lang/Long;->longValue()J
    move-result-wide v1
    invoke-virtual {v0}, Landroid/util/Range;->getUpper()Ljava/lang/Comparable;
    move-result-object v3
    check-cast v3, Ljava/lang/Long;
    invoke-virtual {v3}, Ljava/lang/Long;->longValue()J
    move-result-wide v3
    const/4 v0, 0x1
    invoke-direct {p0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->getMaxShutterSpeed()I
    move-result v5
    :lower
    if-gt v0, v5, :none
    invoke-static {v0}, Lcom/sec/android/app/camera/util/MakerParameter;->getExposureTime(I)J
    move-result-wide v6
    cmp-long v6, v6, v1
    if-gez v6, :upper
    add-int/lit8 v0, v0, 0x1
    goto :lower
    :upper
    if-lt v5, v0, :none
    invoke-static {v5}, Lcom/sec/android/app/camera/util/MakerParameter;->getExposureTime(I)J
    move-result-wide v6
    cmp-long v6, v6, v3
    if-lez v6, :clamp
    add-int/lit8 v5, v5, -0x1
    goto :upper
    :clamp
    invoke-static {p1, v0}, Ljava/lang/Math;->max(II)I
    move-result p1
    invoke-static {p1, v5}, Ljava/lang/Math;->min(II)I
    move-result p1
    return p1
    :none
    const/4 p1, 0x0
    return p1
.end method

.method private preparePublicExposureSettings()V
    .locals 4

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :done
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getIso()I
    move-result v1
    invoke-direct {p0, v1}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicIsoIndex(I)I
    move-result v1
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getShutterSpeed()I
    move-result v2
    invoke-direct {p0, v2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicShutterIndex(I)I
    move-result v2
    if-eqz v1, :auto
    if-nez v2, :apply
    :auto
    const/4 v1, 0x0
    const/4 v2, 0x0
    :apply
    const/4 v3, 0x1
    iput-boolean v3, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    :try_start
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setIso(I)V
    invoke-interface {v0, v2}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setShutterSpeed(I)V
    invoke-direct {p0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->normalizePublicVideoTorch()V
    :try_end
    const/4 v3, 0x0
    iput-boolean v3, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    :done
    return-void
    :cleanup
    move-exception v0
    const/4 v3, 0x0
    iput-boolean v3, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    throw v0
    .catchall {:try_start .. :try_end} :cleanup
.end method

.method private normalizePublicExposureSetting(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)I
    .locals 5

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :unchanged
    iget-boolean v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    if-nez v0, :unchanged
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_ISO:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-eq p1, v1, :eligible
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_SHUTTER_SPEED:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-ne p1, v1, :unchanged
    :eligible
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_ISO:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-ne p1, v1, :current_shutter
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getIso()I
    move-result v1
    goto :current_value
    :current_shutter
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getShutterSpeed()I
    move-result v1
    :current_value
    if-eq p2, v1, :current_event
    return v1
    :current_event
    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    :try_start
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    if-lez p2, :auto
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_ISO:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-ne p1, v1, :shutter
    invoke-direct {p0, p2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicIsoIndex(I)I
    move-result p2
    if-eqz p2, :auto
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getShutterSpeed()I
    move-result v2
    if-nez v2, :clamp_shutter
    iget v2, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mLastNearestShutterSpeed:I
    :clamp_shutter
    invoke-direct {p0, v2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicShutterIndex(I)I
    move-result v2
    if-eqz v2, :not_measured
    move v1, p2
    goto :manual
    :shutter
    invoke-direct {p0, p2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicShutterIndex(I)I
    move-result p2
    if-eqz p2, :auto
    move v2, p2
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getIso()I
    move-result v1
    if-nez v1, :clamp_iso
    iget v1, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mLastNearestIso:I
    :clamp_iso
    invoke-direct {p0, v1}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicIsoIndex(I)I
    move-result v1
    if-eqz v1, :auto
    :manual
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setIso(I)V
    const/4 v3, 0x1
    invoke-direct {p0, v3}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->setShutterPriorityActivate(Z)V
    invoke-interface {v0, v2}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setShutterSpeed(I)V
    invoke-direct {p0, v2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->updateShutterSpeedValue(I)V
    goto :refresh
    :not_measured
    const-string v3, "Pro"
    const-string v4, "Manual ISO waits for a measured shutter value"
    invoke-static {v3, v4}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I
    :auto
    const/4 p2, 0x0
    invoke-interface {v0, p2}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setIso(I)V
    invoke-interface {v0, p2}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setShutterSpeed(I)V
    invoke-direct {p0, p2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->setShutterPriorityActivate(Z)V
    invoke-direct {p0, p2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->updateShutterSpeedValue(I)V
    :refresh
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mBaseMenuController:Lcom/sec/android/app/camera/interfaces/BaseMenuController;
    sget-object v1, Lcom/sec/android/app/camera/interfaces/CommandId;->SHOOTING_MODE_PRO_VIDEO:Lcom/sec/android/app/camera/interfaces/CommandId;
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/BaseMenuController;->refreshQuickSetting(Lcom/sec/android/app/camera/interfaces/CommandId;)V
    :try_end
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    :unchanged
    return p2
    :cleanup
    move-exception v1
    const/4 v0, 0x0
    iput-boolean v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureNormalizing:Z
    throw v1
    .catchall {:try_start .. :try_end} :cleanup
.end method

.method private initPublicIsoSliderRange(Landroid/util/Range;)Z
    .locals 4

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :stock
    invoke-static {p1}, Lorg/lineageos/camera/compat/ProIsoCompat;->indexBounds(Landroid/util/Range;)[I
    move-result-object v0
    if-eqz v0, :unavailable
    const/4 v1, 0x0
    aget v1, v0, v1
    const/4 v2, 0x1
    aget v2, v0, v2
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_ISO:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    invoke-static {v0, v1}, Lcom/sec/android/app/camera/command/CommandIdMap;->getCommandId(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)Lcom/sec/android/app/camera/interfaces/CommandId;
    move-result-object v1
    invoke-static {v0, v2}, Lcom/sec/android/app/camera/command/CommandIdMap;->getCommandId(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)Lcom/sec/android/app/camera/interfaces/CommandId;
    move-result-object v2
    new-instance v0, Landroid/util/Range;
    invoke-direct {v0, v1, v2}, Landroid/util/Range;-><init>(Ljava/lang/Comparable;Ljava/lang/Comparable;)V
    iget-object v1, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mIsoSlider:Lcom/sec/android/app/camera/widget/gl/ProSlider;
    invoke-virtual {v1, v0}, Lcom/sec/android/app/camera/widget/gl/ProSlider;->setRange(Landroid/util/Range;)V
    goto :handled
    :unavailable
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mIsoButton:Lcom/sec/android/app/camera/widget/gl/ProItem;
    const/4 v1, 0x1
    invoke-virtual {v0, v1}, Lcom/sec/android/app/camera/widget/gl/ProItem;->setDim(Z)V
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setClickable(Z)V
    const-string v0, "Exynos9810StockCamera"
    const-string v1, "Manual ISO unavailable: no public sensitivity step"
    invoke-static {v0, v1}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I
    :handled
    const/4 v0, 0x1
    return v0
    :stock
    const/4 v0, 0x0
    return v0
.end method
"""

PRO_VIDEO_EXTRA_HELPERS = r"""
.method private getPublicVideoExposureRange()Landroid/util/Range;
    .locals 3
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mPublicExposureCapability:Lcom/sec/android/app/camera/interfaces/Capability;
    if-eqz v0, :none
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/Capability;->getSensorInfoExposureTimeRange()Landroid/util/Range;
    move-result-object v0
    iget-object v1, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    invoke-interface {v1}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getCamcorderResolution()I
    move-result v1
    invoke-static {v1}, Lcom/sec/android/app/camera/interfaces/Resolution;->getResolution(I)Lcom/sec/android/app/camera/interfaces/Resolution;
    move-result-object v1
    invoke-virtual {v1}, Lcom/sec/android/app/camera/interfaces/Resolution;->getFps()I
    move-result v1
    invoke-static {v0, v1}, Lorg/lineageos/camera/compat/ProVideoCompat;->exposureRange(Landroid/util/Range;I)Landroid/util/Range;
    move-result-object v0
    return-object v0
    :none
    const/4 v0, 0x0
    return-object v0
.end method

.method private initPublicVideoShutterRange()Z
    .locals 4
    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :stock
    const/4 v0, 0x1
    invoke-direct {p0, v0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicShutterIndex(I)I
    move-result v1
    const/16 v0, 0x24
    invoke-direct {p0, v0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->clampPublicShutterIndex(I)I
    move-result v2
    if-eqz v1, :unavailable
    if-eqz v2, :unavailable
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_SHUTTER_SPEED:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    invoke-static {v0, v1}, Lcom/sec/android/app/camera/command/CommandIdMap;->getCommandId(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)Lcom/sec/android/app/camera/interfaces/CommandId;
    move-result-object v1
    invoke-static {v0, v2}, Lcom/sec/android/app/camera/command/CommandIdMap;->getCommandId(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)Lcom/sec/android/app/camera/interfaces/CommandId;
    move-result-object v2
    new-instance v0, Landroid/util/Range;
    invoke-direct {v0, v1, v2}, Landroid/util/Range;-><init>(Ljava/lang/Comparable;Ljava/lang/Comparable;)V
    iget-object v1, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mShutterSpeedSlider:Lcom/sec/android/app/camera/widget/gl/ProSlider;
    invoke-virtual {v1, v0}, Lcom/sec/android/app/camera/widget/gl/ProSlider;->setRange(Landroid/util/Range;)V
    goto :handled
    :unavailable
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mShutterSpeedButton:Lcom/sec/android/app/camera/widget/gl/ProItem;
    const/4 v1, 0x1
    invoke-virtual {v0, v1}, Lcom/sec/android/app/camera/widget/gl/ProItem;->setDim(Z)V
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Lcom/samsung/android/glview/GLView;->setClickable(Z)V
    :handled
    const/4 v0, 0x1
    return v0
    :stock
    const/4 v0, 0x0
    return v0
.end method

.method private resetUnsupportedVideoColorTune()V
    .locals 2
    invoke-static {}, Lorg/lineageos/camera/compat/CameraDeviceCompat;->isSamsungEffectProcessorSupported()Z
    move-result v0
    if-nez v0, :done
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getColorTuneType()I
    move-result v1
    if-eqz v1, :clear
    const/4 v1, 0x0
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setColorTuneType(I)V
    :clear
    const/4 v1, 0x0
    iput v1, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mVideoColorTune:I
    :done
    return-void
.end method

.method private normalizePublicVideoSetting(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)I
    .locals 3
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->VIDEO_COLOR_TUNE_TYPE:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-ne p1, v0, :exposure
    invoke-static {}, Lorg/lineageos/camera/compat/CameraDeviceCompat;->isSamsungEffectProcessorSupported()Z
    move-result v0
    if-nez v0, :done
    invoke-direct {p0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->resetUnsupportedVideoColorTune()V
    const/4 p2, 0x0
    return p2
    :exposure
    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :done
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->BACK_TORCH:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-ne p1, v0, :resolution
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getTorch()I
    move-result v1
    if-ne p2, v1, :current_torch
    invoke-direct {p0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->normalizePublicVideoTorch()V
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getTorch()I
    move-result v1
    :current_torch
    return v1
    :resolution
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->BACK_CAMCORDER_RESOLUTION:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-eq p1, v0, :prepare_resolution
    sget-object v0, Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;->BACK_CAMCORDER_PRO_RESOLUTION:Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;
    if-ne p1, v0, :selection
    :prepare_resolution
    invoke-direct {p0}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->preparePublicExposureSettings()V
    :selection
    invoke-direct {p0, p1, p2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->normalizePublicExposureSetting(Lcom/sec/android/app/camera/interfaces/CameraSettingsBase$Key;I)I
    move-result p2
    :done
    return p2
.end method


.method private normalizePublicVideoTorch()V
    .locals 3
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/ProVideo;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getIso()I
    move-result v1
    if-lez v1, :done
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getShutterSpeed()I
    move-result v1
    if-lez v1, :done
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getTorch()I
    move-result v1
    const/4 v2, 0x1
    if-ne v1, v2, :done
    invoke-direct {p0, v2}, Lcom/sec/android/app/camera/shootingmode/ProVideo;->setPreviousTorchValueAuto(Z)V
    const/4 v1, 0x0
    invoke-interface {v0, v1}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->setTorch(I)V
    :done
    return-void
.end method
"""

PRO_VIDEO_WORKER = r"""
.method public applyPublicProVideoExposure(Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z
    .locals 3
    invoke-direct {p0}, Lcom/sec/android/app/camera/engine/AeAfController;->isPublicProExposure()Z
    move-result v0
    if-eqz v0, :unavailable
    iget-object v0, p0, Lcom/sec/android/app/camera/engine/AeAfController;->mCameraSettings:Lcom/sec/android/app/camera/interfaces/CameraSettings;
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getModeCustomSetting()I
    move-result v1
    const/16 v2, 0x24
    if-ne v1, v2, :unavailable
    iget-object v1, p0, Lcom/sec/android/app/camera/engine/AeAfController;->mEngine:Lcom/sec/android/app/camera/engine/CommonEngine;
    invoke-virtual {v1}, Lcom/sec/android/app/camera/engine/CommonEngine;->getCapability()Lcom/sec/android/app/camera/interfaces/Capability;
    move-result-object v1
    invoke-static {v0, v1, p1}, Lcom/sec/android/app/camera/engine/AeAfController;->applyPublicProVideoExposureSettings(Lcom/sec/android/app/camera/interfaces/CameraSettings;Lcom/sec/android/app/camera/interfaces/Capability;Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z
    move-result v0
    return v0
    :unavailable
    const/4 v0, 0x0
    return v0
.end method

.method public static applyPublicProVideoExposureSettings(Lcom/sec/android/app/camera/interfaces/CameraSettings;Lcom/sec/android/app/camera/interfaces/Capability;Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;)Z
    .locals 10
    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :unavailable
    invoke-interface {p0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getCameraFacing()I
    move-result v0
    const/4 v1, 0x1
    if-ne v0, v1, :unavailable
    move-object v0, p0
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getModeCustomSetting()I
    move-result v1
    const/16 v2, 0x24
    if-ne v1, v2, :unavailable
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getIso()I
    move-result v3
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getShutterSpeed()I
    move-result v1
    if-lez v3, :auto
    if-lez v1, :auto
    invoke-static {v3}, Lcom/sec/android/app/camera/util/MakerParameter;->getSensorSensitivity(I)I
    move-result v3
    invoke-static {v1}, Lcom/sec/android/app/camera/util/MakerParameter;->getExposureTime(I)J
    move-result-wide v4
    if-eqz p1, :auto
    move-object v2, p1
    invoke-interface {v2}, Lcom/sec/android/app/camera/interfaces/Capability;->getSensorInfoSensitivityRange()Landroid/util/Range;
    move-result-object v1
    invoke-interface {v2}, Lcom/sec/android/app/camera/interfaces/Capability;->getSensorInfoExposureTimeRange()Landroid/util/Range;
    move-result-object v2
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getCamcorderResolution()I
    move-result v6
    invoke-static {v6}, Lcom/sec/android/app/camera/interfaces/Resolution;->getResolution(I)Lcom/sec/android/app/camera/interfaces/Resolution;
    move-result-object v6
    invoke-virtual {v6}, Lcom/sec/android/app/camera/interfaces/Resolution;->getFps()I
    move-result v6
    invoke-static/range {v1 .. v6}, Lorg/lineageos/camera/compat/ProVideoCompat;->manualExposure(Landroid/util/Range;Landroid/util/Range;IJI)[J
    move-result-object v0
    if-eqz v0, :auto
    const/4 v8, 0x0
    aget-wide v2, v0, v8
    long-to-int v2, v2
    invoke-static {v2}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v2
    const/4 v8, 0x1
    aget-wide v4, v0, v8
    invoke-static {v4, v5}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v4
    const/4 v8, 0x2
    aget-wide v6, v0, v8
    invoke-static {v6, v7}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v6
    const/4 v1, 0x0
    invoke-static {v1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v1
    goto :torch
    :auto
    move-object v0, p0
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getTorch()I
    move-result v1
    const/4 v8, 0x0
    invoke-static {v1, v8}, Lcom/sec/android/app/camera/util/MakerParameter;->getAeModeByTorchSetting(IZ)I
    move-result v1
    invoke-static {v1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v1
    const/4 v2, 0x0
    invoke-static {v2}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v2
    const-wide/16 v4, 0x0
    invoke-static {v4, v5}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v4
    move-object v6, v4
    :torch
    move-object v0, p0
    invoke-interface {v0}, Lcom/sec/android/app/camera/interfaces/CameraSettings;->getTorch()I
    move-result v0
    invoke-static {v0}, Lcom/sec/android/app/camera/util/MakerParameter;->getFlashMode(I)I
    move-result v0
    invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v0
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_CONTROL_AE_MODE:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v1}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v8
    if-eqz v8, :apply
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_SENSITIVITY:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v2}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v8
    if-eqz v8, :apply
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_EXPOSURE_TIME:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v4}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v8
    if-eqz v8, :apply
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_FRAME_DURATION:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v6}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v8
    if-eqz v8, :apply
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_FLASH_MODE:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v0}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->equals(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Z
    move-result v8
    if-eqz v8, :apply
    :unavailable
    const/4 v8, 0x0
    return v8
    :apply
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_CONTROL_AE_MODE:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v1}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_SENSITIVITY:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v2}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_EXPOSURE_TIME:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v4}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_SENSOR_FRAME_DURATION:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v6}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    sget-object v8, Lcom/samsung/android/camera/core2/MakerPublicKey;->REQUEST_FLASH_MODE:Landroid/hardware/camera2/CaptureRequest$Key;
    invoke-interface {p2, v8, v0}, Lcom/sec/android/app/camera/interfaces/Engine$MakerSettings;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V
    const/4 v8, 0x1
    return v8
.end method
"""

PUBLIC_HIGH_SPEED_LIST_METHOD = r'''
.method private getPublicHighSpeedRequestList(Ljava/util/List;)Ljava/util/List;
    .locals 2

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v0
    if-nez v0, :public_chs_return_stock

    iget-object v0, p0, Lcom/samsung/android/camera/core2/device/CamDeviceImpl;->mCaptureSession:Landroid/hardware/camera2/CameraCaptureSession;
    check-cast v0, Landroid/hardware/camera2/CameraConstrainedHighSpeedCaptureSession;
    const/4 v1, 0x0
    invoke-interface {p1, v1}, Ljava/util/List;->get(I)Ljava/lang/Object;
    move-result-object v1
    check-cast v1, Landroid/hardware/camera2/CaptureRequest;
    invoke-virtual {v0, v1}, Landroid/hardware/camera2/CameraConstrainedHighSpeedCaptureSession;->createHighSpeedRequestList(Landroid/hardware/camera2/CaptureRequest;)Ljava/util/List;
    move-result-object p1

    :public_chs_return_stock
    return-object p1
.end method
'''


def patch_public_slow_motion(decoded):
    path = Path(decoded) / 'smali/com/samsung/android/camera/core2/device/CamDeviceImpl.smali'
    text = path.read_text()
    if 'getPublicHighSpeedRequestList' in text or ':public_chs_' in text:
        raise ValueError('Expected unmodified high-speed session implementation')

    def edit(signature, callback):
        nonlocal text
        pattern = re.compile(r'(?ms)^\.method [^\n]*' + re.escape(signature) + r'\n.*?^\.end method\n')
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError('Expected one high-speed method ' + signature)
        old = matches[0].group(0)
        new = callback(old)
        if old == new:
            raise ValueError('No high-speed method change ' + signature)
        text = text[:matches[0].start()] + new + text[matches[0].end():]

    def once(body, old, new):
        if body.count(old) != 1:
            raise ValueError('Expected one high-speed instruction block: ' + old[:80])
        return body.replace(old, new, 1)

    def session(body):
        old = '''    iget-object v1, p1, Lcom/samsung/android/camera/core2/CamDevice$SessionConfig;->previewCbConfig:Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$PreviewCbConfig;

    invoke-direct {p0, v1}, Lcom/samsung/android/camera/core2/device/CamDeviceImpl;->preparePreviewImageReaders(Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$PreviewCbConfig;)V'''
        new = '''    iget-object v1, p1, Lcom/samsung/android/camera/core2/CamDevice$SessionConfig;->previewCbConfig:Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$PreviewCbConfig;

    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v3
    if-nez v3, :public_chs_callback_config_ready

    new-instance v1, Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$PreviewCbConfig;
    const/4 v3, 0x0
    invoke-direct {v1, v3, v3}, Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$PreviewCbConfig;-><init>(Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$ImageCbConfig;Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$ImageCbConfig;)V

    :public_chs_callback_config_ready
    invoke-direct {p0, v1}, Lcom/samsung/android/camera/core2/device/CamDeviceImpl;->preparePreviewImageReaders(Lcom/samsung/android/camera/core2/CamDevice$SessionConfig$PreviewCbConfig;)V'''
        return once(body, old, new)

    def repeating(body, record):
        callbacks = ('v7', 'v8') if record else ('v6', 'v7')
        extra = 'v10' if record else 'v9'
        owner = 'record' if record else 'preview'
        insertion = f'''    invoke-static {{}}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v1
    if-nez v1, :public_chs_{owner}_counts_ready
    const/4 {callbacks[0]}, 0x0
    const/4 {callbacks[1]}, 0x0
    iget-object v1, v0, Lcom/samsung/android/camera/core2/device/CamDeviceImpl;->mPreviewSurface:Landroid/view/Surface;
    if-eqz v1, :public_chs_{owner}_counts_ready
    const/4 {extra}, 0x0
    :public_chs_{owner}_counts_ready

'''
        body = once(body, '    :try_start_0\n', '    :try_start_0\n' + insertion)
        if record:
            # v4 is dead after the last target constructor; retain all existing live v13/v14 flags.
            old = '    invoke-static {v15, v3, v1, v2, v14}, Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;->createCaptureRequestGroup(Ljava/util/List;IJZ)Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;'
            new = '''    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v4
    invoke-static {v15, v3, v1, v2, v4}, Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;->createCaptureRequestGroup(Ljava/util/List;IJZ)Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;'''
        else:
            # v15 is dead after the final target constructor; v13 remains the existing true flag.
            old = '    invoke-static {v14, v12, v1, v2, v13}, Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;->createCaptureRequestGroup(Ljava/util/List;IJZ)Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;'
            new = '''    invoke-static {}, Lorg/lineageos/camera/compat/AndroidCompat;->hasSamsungStreamOptions()Z
    move-result v15
    invoke-static {v14, v12, v1, v2, v15}, Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;->createCaptureRequestGroup(Ljava/util/List;IJZ)Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;'''
        body = once(body, old, new)
        old = '''    invoke-virtual {v1}, Lcom/samsung/android/camera/core2/device/CamDeviceCaptureRequestGroup;->getCaptureRequestList()Ljava/util/List;

    move-result-object v1'''
        new = old + '''

    invoke-direct {v0, v1}, Lcom/samsung/android/camera/core2/device/CamDeviceImpl;->getPublicHighSpeedRequestList(Ljava/util/List;)Ljava/util/List;
    move-result-object v1'''
        return once(body, old, new)

    edit('createHighSpeedCaptureSession(Lcom/samsung/android/camera/core2/CamDevice$SessionConfig;)V', session)
    edit('startHighSpeedPreviewRepeating(IIIILcom/samsung/android/camera/core2/CamDevice$PreviewStateCallback;)I', lambda b: repeating(b, False))
    edit('startHighSpeedRecordRepeating(IIIIILcom/samsung/android/camera/core2/CamDevice$RecordStateCallback;)I', lambda b: repeating(b, True))
    path.write_text(text + '\n' + PUBLIC_HIGH_SPEED_LIST_METHOD)


PANORAMA_PREVIEW_METHOD = '''.method private postLivePreview(Lcom/samsung/android/camera/core2/util/ImageBuffer;)Z
    .locals 9

    invoke-virtual {p1}, Lcom/samsung/android/camera/core2/util/ImageBuffer;->rentByteBuffer()Ljava/nio/ByteBuffer;
    move-result-object v0

    :public_preview_start
    invoke-virtual {p1}, Lcom/samsung/android/camera/core2/util/ImageBuffer;->getImageInfo()Lcom/samsung/android/camera/core2/util/ImageInfo;
    move-result-object v7
    invoke-virtual {v7}, Lcom/samsung/android/camera/core2/util/ImageInfo;->getStrideInfo()Lcom/samsung/android/camera/core2/util/ImageInfo$StrideInfo;
    move-result-object v7

    iget-object v8, p0, Lcom/samsung/android/camera/core2/node/panorama/PanoramaNode;->mInitParam:Lcom/samsung/android/camera/core2/node/panorama/PanoramaNodeBase$PanoramaInitParam;
    iget-object v8, v8, Lcom/samsung/android/camera/core2/node/panorama/PanoramaNodeBase$PanoramaInitParam;->previewSize:Landroid/util/Size;
    invoke-virtual {v8}, Landroid/util/Size;->getWidth()I
    move-result v1
    invoke-virtual {v8}, Landroid/util/Size;->getHeight()I
    move-result v2
    invoke-virtual {v7}, Lcom/samsung/android/camera/core2/util/ImageInfo$StrideInfo;->getRowStride()I
    move-result v3
    invoke-virtual {v7}, Lcom/samsung/android/camera/core2/util/ImageInfo$StrideInfo;->getHeightSlice()I
    move-result v4

    iget-object v8, p0, Lcom/samsung/android/camera/core2/node/panorama/PanoramaNode;->mScaledPreviewSize:Landroid/util/Size;
    invoke-virtual {v8}, Landroid/util/Size;->getWidth()I
    move-result v5
    invoke-virtual {v8}, Landroid/util/Size;->getHeight()I
    move-result v6
    invoke-static/range {v0 .. v6}, Lorg/lineageos/camera/compat/PanoramaCompat;->resizeNv21ToExtendedRgba(Ljava/nio/ByteBuffer;IIIIII)[B
    move-result-object v7
    :public_preview_end
    .catchall {:public_preview_start .. :public_preview_end} :public_preview_error

    invoke-virtual {p1, v0}, Lcom/samsung/android/camera/core2/util/ImageBuffer;->returnByteBuffer(Ljava/nio/ByteBuffer;)V
    if-eqz v7, :public_preview_invalid

    iget-object v8, p0, Lcom/samsung/android/camera/core2/node/panorama/PanoramaNode;->mNodeCallback:Lcom/samsung/android/camera/core2/node/panorama/PanoramaNodeBase$NodeCallback;
    invoke-interface {v8, v7}, Lcom/samsung/android/camera/core2/node/panorama/PanoramaNodeBase$NodeCallback;->onPanoramaLivePreviewData([B)V
    const/4 v0, 0x1
    return v0

    :public_preview_invalid
    sget-object v8, Lcom/samsung/android/camera/core2/node/panorama/PanoramaNode;->SEC_PANORAMA_TAG:Lcom/samsung/android/camera/core2/util/CLog$Tag;
    const-string v7, "postLivePreview fail - invalid NV21 preview buffer"
    invoke-static {v8, v7}, Lcom/samsung/android/camera/core2/util/CLog;->e(Lcom/samsung/android/camera/core2/util/CLog$Tag;Ljava/lang/String;)V
    const/4 v0, 0x0
    return v0

    :public_preview_error
    move-exception v7
    invoke-virtual {p1, v0}, Lcom/samsung/android/camera/core2/util/ImageBuffer;->returnByteBuffer(Ljava/nio/ByteBuffer;)V
    throw v7
.end method
'''

def patch_panorama_live_preview(decoded):
    path = Path(decoded) / 'smali/com/samsung/android/camera/core2/node/panorama/PanoramaNode.smali'
    text = path.read_text()
    pattern = re.compile(r'(?ms)^\.method private postLivePreview\(Lcom/samsung/android/camera/core2/util/ImageBuffer;\)Z\n.*?^\.end method\n')
    matches = list(pattern.finditer(text))
    if len(matches) != 1 or 'PanoramaCompat;' in text:
        raise ValueError('Unexpected Panorama live-preview method')
    original = matches[0].group(0)
    expected = 'Lcom/samsung/android/camera/core2/util/ImageUtils;->quramResizeNV21ToRGBA('
    contract = {
        expected: 1,
        '->getRowStride()I': 1,
        '->getHeightSlice()I': 1,
        '->mInitParam:Lcom/samsung/android/camera/core2/node/panorama/PanoramaNodeBase$PanoramaInitParam;': 2,
        '->mScaledPreviewSize:Landroid/util/Size;': 2,
        '->onPanoramaLivePreviewData([B)V': 1,
    }
    if any(original.count(token) != count for token, count in contract.items()):
        raise ValueError('Unexpected Panorama preview conversion contract')
    text = pattern.sub(lambda _: PANORAMA_PREVIEW_METHOD, text, count=1)
    path.write_text(text)


def patch_decoded(decoded, mappings):
    counts = {}
    methods = {item["after_type_remap"]: item for item in mappings["methods"]}
    invoke = re.compile(r"(invoke-(?:virtual|interface|static)(/range)?)(\s+\{[^}]*\},\s+)(\S+)")
    for path in sorted(decoded.glob("smali*/**/*.smali")):
        text = path.read_text()
        for old, new in mappings["type_map"].items():
            text = text.replace(old, new)

        def replace_call(match):
            target = match[4]
            if target not in methods:
                return match[0]
            item = methods[target]
            original_kind = match[1].split("/")[0].removeprefix("invoke-")
            if original_kind != item["original_invoke"]:
                raise ValueError(f"Unexpected invocation: {path}: {match[0]}")
            counts[item["original"]] = counts.get(item["original"], 0) + 1
            return "invoke-static" + (match[2] or "") + match[3] + item["replacement"]

        text = invoke.sub(replace_call, text)
        # Stock EnclosingMethod annotations retain pre-desugaring names for
        # these two callbacks; their executable targets already use the suffix.
        text = text.replace("->lambda$hideTextBalloon$0()V",
                            "->lambda$hideTextBalloon$0$TextBalloon()V")
        text = text.replace("->lambda$showLocationTagPopupInSecureLock$4(",
                            "->lambda$showLocationTagPopupInSecureLock$4$PreferenceSettingFragment(")
        for old, new in mappings.get("string_replacements", {}).items():
            text = text.replace('"' + old + '"', '"' + new + '"')
        text = text.replace("Landroid/os/UserHandle;->SEM_ALL:",
                            "Landroid/os/UserHandle;->ALL:")
        for field, value in (("SEM_INT", "0xb57"),
                             ("SEM_PLATFORM_INT", "0x1afa4")):
            text = re.sub(r"sget (\w+), Landroid/os/Build\$VERSION;->" + field + r":I",
                          r"const \1, " + value, text)
        text = re.sub(r"iget (\w+), \w+, Landroid/content/res/Configuration;->semDesktopModeEnabled:I",
                      r"const/4 \1, 0x0", text)
        text = re.sub(r"iput \w+, \w+, Landroid/app/Notification;->semPriority:I",
                      "nop # Samsung-only priority is absent on AOSP", text)
        text = re.sub(r"iput \w+, \w+, Landroid/view/WindowManager\$LayoutParams;->coverMode:I",
                      "nop # Samsung cover mode is disabled on this platform", text)
        text = text.replace('"/system/cameradata',
                            '"/system_ext/etc/camera')
        path.write_text(text)
    patch_runtime_methods(decoded)
    patch_pro_exposure(decoded)
    patch_unavailable_effect_pdk(decoded)
    patch_public_pro_iso(decoded)
    patch_public_pro_iso_range(decoded)
    patch_public_video_requests(decoded)
    patch_public_pro_video(decoded)
    patch_public_slow_motion(decoded)
    patch_panorama_live_preview(decoded)
    patch_gl_spr_loader(decoded)
    adapt_spinner_dropdown_layout(decoded)
    patch_preview_snapshot(decoded)
    patch_media_store(decoded)
    patch_recording_orientation(decoded)
    patch_single_photo_shutter(decoded)
    adapt_optional_scene_toast(decoded)
    patch_front_camera_device_id(decoded)
    patch_front_fallback_active_array(decoded)
    patch_gallery_viewer(decoded)
    patch_recording_progress(decoded)
    patch_telephoto(decoded)
    manifest = decoded / "AndroidManifest.xml"
    xml = ET.parse(manifest)
    application = xml.getroot().find("application")
    for node in list(application):
        if node.tag == "uses-library" and node.get(ANDROID + "name") in (
                "semextendedformat", "secimaging"):
            application.remove(node)
    # Bixby is disabled; its SDK provider has no supported caller here.
    for node in list(application):
        name = node.get(ANDROID + "name", "")
        if ((node.tag == "provider" and name ==
             "com.samsung.android.sdk.bixby2.provider.CapsuleProvider") or
            (node.tag == "meta-data" and name in (
             "com.samsung.android.bixby.service.sdk.version",
             "com.samsung.android.bixby.service.sdk.version_code"))):
            application.remove(node)
    # The app-local disabled recognizer never records a hotword source.
    for node in list(xml.getroot()):
        if node.tag == "uses-permission" and node.get(ANDROID + "name") in (
                "android.permission.CAPTURE_AUDIO_HOTWORD",
                "com.samsung.android.bixby.agent.permission.RECEIVE_BIXBY_VIEW_STATE"):
            xml.getroot().remove(node)
    application.set(ANDROID + "label", "Samsung Camera")
    # Stock targetSdk29 code still reads EXIF/SEF and renames via _data.
    application.set(ANDROID + "requestLegacyExternalStorage", "true")
    for component in application:
        if component.tag in ("activity", "activity-alias") and any(
                category.get(ANDROID + "name") == "android.intent.category.LAUNCHER"
                for category in component.iter("category")):
            component.set(ANDROID + "label", "Samsung Camera")
    xml.write(manifest, encoding="utf-8", xml_declaration=True)
    marker = decoded / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"port": 14, "modes": ["photo", "video", "pro"],
                                 "available_experimental_modes": ["pro_video", "panorama", "slow_motion"],
                                 "android_api_call_counts": counts}, indent=2) + "\n")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--secimaging", required=True, type=Path)
    parser.add_argument("--semextendedformat", required=True, type=Path)
    parser.add_argument("--sprengine", required=True, type=Path)
    parser.add_argument("--aosp-framework", required=True, type=Path)
    parser.add_argument("--apktool", required=True, type=Path)
    parser.add_argument("--java", default="java")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    mappings = json.loads((HERE / "android-api-mapping.json").read_text())
    with tempfile.TemporaryDirectory(prefix="stock-camera-port-") as temporary:
        work = args.work_dir or Path(temporary)
        work.mkdir(parents=True, exist_ok=True)
        aosp_cache = work / "aosp-framework"
        apktool = [args.java, "-jar", args.apktool]
        run(*apktool, "if", args.aosp_framework, "-p", aosp_cache)
        decoded = work / "decoded"
        run(*apktool, "d", args.apk, "-f", "-p", aosp_cache, "-o", decoded)
        for index, jar in enumerate((args.secimaging, args.semextendedformat, args.sprengine), 3):
            jar_dir = work / ("jar-" + str(index))
            run(*apktool, "d", jar, "-f", "-r", "-o", jar_dir)
            shutil.copytree(jar_dir / "smali", decoded / ("smali_classes" + str(index)))
        counts = patch_decoded(decoded, mappings)
        missing = set(item["original"] for item in mappings["methods"]) - counts.keys()
        if missing:
            raise ValueError(f"Stock APK does not match mapped APIs: {sorted(missing)}")
        built = work / "built.apk"
        run(*apktool, "b", decoded, "-p", aosp_cache, "-o", built)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # Normalize metadata while preserving stored native libraries. Soong
        # performs final alignment and signing after app-local DEX is appended.
        with zipfile.ZipFile(built) as source, zipfile.ZipFile(args.out, "w") as output:
            for name in sorted(source.namelist()):
                original = source.getinfo(name)
                item = zipfile.ZipInfo(name, (2009, 1, 1, 0, 0, 0))
                item.compress_type = original.compress_type
                item.external_attr = 0o100644 << 16
                output.writestr(item, source.read(name))


if __name__ == "__main__":
    main()
