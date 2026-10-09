# Copyright (C) 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Adapt file-based panorama rows after the ordinary MediaStore patch."""

from pathlib import Path

E = 'Lcom/sec/android/app/camera/engine/CommonEngine;'
T = 'Lcom/sec/android/app/camera/engine/PictureProcessor$PictureSavingTask;'
P = 'Lcom/sec/android/app/camera/engine/PictureProcessor;'
C = 'Lorg/lineageos/camera/compat/MediaStoreCompat;'
H = 'Lorg/lineageos/camera/compat/MediaStoreCompat$PendingImage;'


def _method(text, declaration):
    if text.count(declaration + '\n') != 1:
        raise ValueError(f'Expected one panorama method: {declaration}')
    start = text.index(declaration + '\n')
    end = text.index('.end method', start) + len('.end method')
    return text[start:end]


def _once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f'Unexpected panorama method layout: {before[:100]}')
    return text.replace(before, after)


def patch_panorama_storage(decoded: Path):
    engine_dir = decoded / 'smali_classes2/com/sec/android/app/camera/engine'
    engine_path = engine_dir / 'CommonEngine.smali'
    task_path = engine_dir / 'PictureProcessor$PictureSavingTask.smali'
    request_path = engine_dir / 'request/StartStitchingCaptureRequest.smali'
    processor_path = engine_dir / 'PictureProcessor.smali'
    engine, task, request, processor = (p.read_text() for p in
                                      (engine_path, task_path, request_path, processor_path))
    field = f'.field private volatile mPendingPanoramaImage:{H}\n'
    engine = _once(engine, '# direct methods', field +
                   '.field private volatile mPanoramaCaptureAccepted:Z\n\n# direct methods')
    task = _once(task, '# direct methods', field + '\n# direct methods')

    start = _method(engine, '.method private startStitchingCapture()V')
    begin = start.index('    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I')
    end = start.index('    :cond_0', begin)
    start = start[:begin] + start[end:]
    start = _once(start, '    .locals 2', f'''    .locals 2

    const/4 v0, 0x1

    iput-boolean v0, p0, {E}->mPanoramaCaptureAccepted:Z''')
    engine = engine.replace(_method(engine, '.method private startStitchingCapture()V'), start)

    panorama_path = decoded / 'smali_classes2/com/sec/android/app/camera/shootingmode/Panorama.smali'
    panorama = panorama_path.read_text()
    declaration = '.method public onShutterKeyReleased(Lcom/sec/android/app/camera/interfaces/CameraContext$InputType;)Z'
    old = _method(panorama, declaration)
    hook = f'''    :cond_1
    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/Panorama;->mEngine:Lcom/sec/android/app/camera/interfaces/Engine;

    check-cast v0, {E}

    invoke-virtual {{v0}}, {E}->preparePendingPanoramaImage()Z

    move-result v0

    if-nez v0, :panorama_preflight_ready

    return v2

    :panorama_preflight_ready'''
    new = _once(old, '    :cond_1', hook)
    call = '    invoke-interface {v0, p1, v1}, Lcom/sec/android/app/camera/interfaces/Engine;->handleShutterReleased(Lcom/sec/android/app/camera/interfaces/CameraContext$InputType;Lcom/sec/android/app/camera/interfaces/Engine$CaptureType;)V'
    new = _once(new, call, call + f'''

    iget-object v0, p0, Lcom/sec/android/app/camera/shootingmode/Panorama;->mEngine:Lcom/sec/android/app/camera/interfaces/Engine;

    check-cast v0, {E}

    invoke-virtual {{v0}}, {E}->isPanoramaCaptureAccepted()Z

    move-result v1

    if-nez v1, :panorama_shutter_accepted

    invoke-virtual {{v0}}, {E}->cancelPendingPanoramaImage()V

    invoke-direct {{p0}}, Lcom/sec/android/app/camera/shootingmode/Panorama;->reset()V

    return v2

    :panorama_shutter_accepted''')
    panorama = panorama.replace(old, new)

    methods = f'''
.method public preparePendingPanoramaImage()Z
    .locals 2

    const/4 v0, 0x0

    iput-boolean v0, p0, {E}->mPanoramaCaptureAccepted:Z

    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I

    const/16 v1, 0x1d

    if-gt v0, v1, :panorama_prepare_modern

    const/4 v0, 0x1

    return v0

    :panorama_prepare_modern
    invoke-direct {{p0}}, {E}->insertPendingPanoramaImage()Z

    move-result v0

    if-nez v0, :panorama_prepare_done

    invoke-virtual {{p0}}, {E}->getGenericEventListener()Lcom/sec/android/app/camera/interfaces/Engine$GenericEventListener;

    move-result-object v0

    if-eqz v0, :panorama_prepare_failed

    invoke-interface {{v0}}, Lcom/sec/android/app/camera/interfaces/Engine$GenericEventListener;->onPictureSavingFailed()V

    :panorama_prepare_failed
    const/4 v0, 0x0

    :panorama_prepare_done
    return v0
.end method

.method public isPanoramaCaptureAccepted()Z
    .locals 1

    iget-boolean v0, p0, {E}->mPanoramaCaptureAccepted:Z

    return v0
.end method

.method private markPanoramaTimerAccepted()V
    .locals 2

    iget-object v0, p0, {E}->mCaptureType:Lcom/sec/android/app/camera/interfaces/Engine$CaptureType;

    sget-object v1, Lcom/sec/android/app/camera/interfaces/Engine$CaptureType;->STITCHING_CAPTURE:Lcom/sec/android/app/camera/interfaces/Engine$CaptureType;

    if-ne v0, v1, :panorama_timer_other_capture

    const/4 v0, 0x1

    iput-boolean v0, p0, {E}->mPanoramaCaptureAccepted:Z

    :panorama_timer_other_capture
    return-void
.end method

.method private insertPendingPanoramaImage()Z
    .locals 7

    invoke-virtual {{p0}}, {E}->cancelPendingPanoramaImage()V

    :panorama_insert_try
    sget-object v0, Lcom/sec/android/app/camera/interfaces/InternalEngine$PictureSavingType;->JPEG:Lcom/sec/android/app/camera/interfaces/InternalEngine$PictureSavingType;

    invoke-virtual {{p0, v0}}, {E}->createNewOutputFilePath(Lcom/sec/android/app/camera/interfaces/InternalEngine$PictureSavingType;)V

    iget-object v1, p0, {E}->mOutputFilePath:Ljava/lang/String;

    new-instance v2, Ljava/io/File;

    invoke-direct {{v2, v1}}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    invoke-virtual {{v2}}, Ljava/io/File;->getName()Ljava/lang/String;

    move-result-object v2

    new-instance v3, Landroid/content/ContentValues;

    invoke-direct {{v3}}, Landroid/content/ContentValues;-><init>()V

    const-string v4, "_display_name"

    invoke-virtual {{v3, v4, v2}}, Landroid/content/ContentValues;->put(Ljava/lang/String;Ljava/lang/String;)V

    invoke-static {{v2}}, Lcom/sec/android/app/camera/util/Util;->getFileNameWithoutExtension(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v2

    const-string v4, "title"

    invoke-virtual {{v3, v4, v2}}, Landroid/content/ContentValues;->put(Ljava/lang/String;Ljava/lang/String;)V

    const-string v4, "mime_type"

    const-string v2, "image/jpeg"

    invoke-virtual {{v3, v4, v2}}, Landroid/content/ContentValues;->put(Ljava/lang/String;Ljava/lang/String;)V

    const/4 v2, 0x2

    invoke-static {{v1, v2}}, Lcom/sec/android/app/camera/util/StorageUtils;->replaceSDStoragePath(Ljava/lang/String;I)Ljava/lang/String;

    move-result-object v2

    const-string v4, "_data"

    invoke-virtual {{v3, v4, v2}}, Landroid/content/ContentValues;->put(Ljava/lang/String;Ljava/lang/String;)V

    iget-object v2, p0, {E}->mPictureProcessor:{P}

    invoke-virtual {{v2, v0}}, {P}->getPictureSavingStorage(Lcom/sec/android/app/camera/interfaces/InternalEngine$PictureSavingType;)I

    move-result v0

    sget-object v2, Landroid/provider/MediaStore$Images$Media;->EXTERNAL_CONTENT_URI:Landroid/net/Uri;

    invoke-static {{v2, v0}}, Lcom/sec/android/app/camera/util/StorageUtils;->getContentUri(Landroid/net/Uri;I)Landroid/net/Uri;

    move-result-object v2

    iget-object v0, p0, {E}->mCameraContext:Lcom/sec/android/app/camera/interfaces/CameraContext;

    invoke-interface {{v0}}, Lcom/sec/android/app/camera/interfaces/CameraContext;->getContext()Landroid/content/Context;

    move-result-object v0

    invoke-virtual {{v0}}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;

    move-result-object v0

    invoke-static {{v0, v2, v3, v1}}, {C}->insertPendingFile(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;Ljava/lang/String;){H}

    move-result-object v0

    iput-object v0, p0, {E}->mPendingPanoramaImage:{H}

    invoke-virtual {{v0}}, {H}->getPath()Ljava/lang/String;

    move-result-object v1

    iput-object v1, p0, {E}->mOutputFilePath:Ljava/lang/String;

    invoke-virtual {{v0}}, {H}->getUri()Landroid/net/Uri;

    move-result-object v0

    iget-object v1, p0, {E}->mLastContentData:Lcom/sec/android/app/camera/engine/LastContentData;

    invoke-virtual {{v1}}, Lcom/sec/android/app/camera/engine/LastContentData;->clear()V

    invoke-virtual {{v1, v0}}, Lcom/sec/android/app/camera/engine/LastContentData;->setContentUriForReading(Landroid/net/Uri;)V

    invoke-virtual {{v1, v0}}, Lcom/sec/android/app/camera/engine/LastContentData;->setContentUriForWriting(Landroid/net/Uri;)V

    sget-object v0, Lcom/sec/android/app/camera/interfaces/Engine$ContentData$Type;->IMAGE:Lcom/sec/android/app/camera/interfaces/Engine$ContentData$Type;

    invoke-virtual {{v1, v0}}, Lcom/sec/android/app/camera/engine/LastContentData;->setContentType(Lcom/sec/android/app/camera/interfaces/Engine$ContentData$Type;)V
    :panorama_insert_end
    .catch Ljava/lang/RuntimeException; {{:panorama_insert_try .. :panorama_insert_end}} :panorama_insert_error

    const/4 v0, 0x1

    return v0

    :panorama_insert_error
    move-exception v0

    const-string v1, "CommonEngine"

    const-string v2, "Could not create a pending panorama image"

    invoke-static {{v1, v2, v0}}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    invoke-virtual {{p0}}, {E}->cancelPendingPanoramaImage()V

    const/4 v0, 0x0

    return v0
.end method

.method public cancelPendingPanoramaImage()V
    .locals 3

    iget-object v0, p0, {E}->mPendingPanoramaImage:{H}

    if-eqz v0, :panorama_cancel_done

    invoke-virtual {{v0}}, {H}->cancel()V

    invoke-virtual {{v0}}, {H}->isClaimed()Z

    move-result v1

    if-nez v1, :panorama_cancel_done

    iget-object v1, p0, {E}->mLastContentData:Lcom/sec/android/app/camera/engine/LastContentData;

    invoke-virtual {{v1}}, Lcom/sec/android/app/camera/engine/LastContentData;->getContentUriForWriting()Landroid/net/Uri;

    move-result-object v2

    if-eqz v2, :panorama_cancel_done

    invoke-virtual {{v0}}, {H}->getUri()Landroid/net/Uri;

    move-result-object v0

    invoke-virtual {{v2, v0}}, Landroid/net/Uri;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-eqz v0, :panorama_cancel_done

    invoke-virtual {{v1}}, Lcom/sec/android/app/camera/engine/LastContentData;->clear()V

    :panorama_cancel_done
    return-void
.end method

.method public getPendingPanoramaImage(Ljava/lang/String;){H}
    .locals 2

    iget-object v0, p0, {E}->mPendingPanoramaImage:{H}

    if-eqz v0, :panorama_pending_absent

    invoke-virtual {{v0, p1}}, {H}->matches(Ljava/lang/String;)Z

    move-result v1

    if-eqz v1, :panorama_pending_absent

    return-object v0

    :panorama_pending_absent
    const/4 v0, 0x0

    return-object v0
.end method
'''
    engine += methods
    old = _method(engine, '.method public handleShutterReleased(Lcom/sec/android/app/camera/interfaces/CameraContext$InputType;Lcom/sec/android/app/camera/interfaces/Engine$CaptureType;)V')
    timer_return = '    invoke-static {v1, v3}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I\n\n    return-void'
    if old.count(timer_return) != 2:
        raise ValueError('Expected both accepted shutter timer branches')
    new = old.replace(timer_return, f'    invoke-direct {{p0}}, {E}->markPanoramaTimerAccepted()V\n\n' + timer_return)
    engine = engine.replace(old, new)
    for declaration in ('.method public handleCameraError(I)V', '.method private stopPictureProcessor()V',
                        '.method cancelShutterTimerCapture()V'):
        old = _method(engine, declaration)
        new = old
        # Insert before the first original instruction, leaving parameters untouched.
        marker = '\n\n'
        pos = new.index(marker, new.index('    .locals ')) + len(marker)
        new = new[:pos] + f'    invoke-virtual {{p0}}, {E}->cancelPendingPanoramaImage()V\n\n' + new[pos:]
        engine = engine.replace(old, new)

    # Do not delete a file whose pending row has been handed to the saving task.
    old = _method(engine, '.method private removeOutputFilePath()V')
    prefix = f'''
    iget-object v0, p0, {E}->mOutputFilePath:Ljava/lang/String;

    invoke-virtual {{p0, v0}}, {E}->getPendingPanoramaImage(Ljava/lang/String;){H}

    move-result-object v0

    if-eqz v0, :panorama_remove_original

    invoke-virtual {{v0}}, {H}->isClaimed()Z

    move-result v0

    if-eqz v0, :panorama_remove_original

    return-void

    :panorama_remove_original
    invoke-virtual {{p0}}, {E}->cancelPendingPanoramaImage()V
'''
    engine = engine.replace(old, _once(old, '    .locals 3\n', '    .locals 3\n' + prefix))

    # The pathname was created before the pending insert on modern Android.
    ctor_decl = '.method constructor <init>(Lcom/sec/android/app/camera/engine/request/MakerHolder;Lcom/sec/android/app/camera/interfaces/InternalEngine;Lcom/sec/android/app/camera/engine/request/RequestId;)V'
    old = _method(request, ctor_decl)
    new = _once(old, '    .locals 0', '    .locals 1')
    needle = '    .line 51\n'
    new = _once(new, needle, '''    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I

    const/16 p3, 0x1d

    if-gt v0, p3, :panorama_path_ready

''' + needle)
    new = _once(new, '    return-void', '    :panorama_path_ready\n    return-void')
    request = request.replace(old, new)

    # Bind the file-saving task to its capture row before it enters the executor.
    ctor_decl = '.method constructor <init>(Lcom/sec/android/app/camera/engine/PictureProcessor;Ljava/lang/String;Ljava/lang/String;JILcom/sec/android/app/camera/interfaces/InternalEngine$PictureSavingType;)V'
    old = _method(task, ctor_decl)
    hook = f'''    iget-object v0, p0, {T}->this$0:{P}

    invoke-static {{v0}}, {P}->access$300({P}){E}

    move-result-object v0

    iget-object p1, p0, {T}->mFilePath:Ljava/lang/String;

    invoke-virtual {{v0, p1}}, {E}->getPendingPanoramaImage(Ljava/lang/String;){H}

    move-result-object v0

    iput-object v0, p0, {T}->mPendingPanoramaImage:{H}

    if-eqz v0, :panorama_task_ready

    invoke-virtual {{v0, p1}}, {H}->claim(Ljava/lang/String;)Landroid/net/Uri;

    move-result-object v0

    iput-object v0, p0, {T}->mUri:Landroid/net/Uri;

    :panorama_task_ready
    return-void'''
    old_ctor = old
    old = _once(old, '    .locals 1', '    .locals 3')
    hook = hook.replace('    :panorama_task_ready', f'''    iget-object v0, p0, {T}->mPendingPanoramaImage:{H}

    invoke-virtual {{v0}}, {H}->getDateTaken()J

    move-result-wide v1

    iput-wide v1, p0, {T}->mDateTaken:J

    :panorama_task_ready''')
    task = task.replace(old_ctor, _once(old, '    return-void', hook))

    # Ordinary ByteBuffer saving keeps its existing publishing path.
    old = _method(task, '.method private updateToDB(Landroid/content/ContentValues;)V')
    before = f'''    iget-object p0, p0, {T}->mUri:Landroid/net/Uri;

    invoke-static {{v2, p0, p1}}, {C}->publish(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;)I'''
    task = task.replace(old, _once(old, before, f'    invoke-direct {{p0, p1}}, {T}->publishFileOrImage(Landroid/content/ContentValues;)I'))
    old = _method(task, '.method public run()V')
    call = f'    invoke-direct {{p0, v1}}, {T}->updateToDB(Landroid/content/ContentValues;)V'
    if old.count(call) != 2:
        raise ValueError('Expected both file-image save branches')
    new = old.replace(call, f'    invoke-direct {{p0, v1}}, {T}->saveFileImage(Landroid/content/ContentValues;)Z\n\n    move-result v3')
    task = task.replace(old, new)
    task += f'''
.method private publishFileOrImage(Landroid/content/ContentValues;)I
    .locals 2

    iget-object v0, p0, {T}->mPendingPanoramaImage:{H}

    if-eqz v0, :panorama_publish_ordinary

    invoke-virtual {{v0, p1}}, {H}->publish(Landroid/content/ContentValues;)I

    move-result v1

    invoke-virtual {{v0}}, {H}->getPath()Ljava/lang/String;

    move-result-object v0

    iput-object v0, p0, {T}->mFilePath:Ljava/lang/String;

    iget-object v0, p0, {T}->mPendingPanoramaImage:{H}

    invoke-virtual {{v0}}, {H}->getDisplayName()Ljava/lang/String;

    move-result-object v0

    iput-object v0, p0, {T}->mFileName:Ljava/lang/String;

    return v1

    :panorama_publish_ordinary
    iget-object v0, p0, {T}->this$0:{P}

    invoke-static {{v0}}, {P}->access$1200({P})Landroid/content/ContentResolver;

    move-result-object v0

    iget-object v1, p0, {T}->mUri:Landroid/net/Uri;

    invoke-static {{v0, v1, p1}}, {C}->publish(Landroid/content/ContentResolver;Landroid/net/Uri;Landroid/content/ContentValues;)I

    move-result v0

    return v0
.end method

.method private saveFileImage(Landroid/content/ContentValues;)Z
    .locals 3

    :panorama_save_try
    iget-object v0, p0, {T}->mPendingPanoramaImage:{H}

    if-eqz v0, :panorama_save_update

    iget-object v0, p0, {T}->mUri:Landroid/net/Uri;

    if-nez v0, :panorama_save_update

    new-instance v0, Ljava/lang/IllegalStateException;

    const-string v1, "Panorama row was cancelled before saving"

    invoke-direct {{v0, v1}}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V

    throw v0

    :panorama_save_update
    invoke-direct {{p0, p1}}, {T}->updateToDB(Landroid/content/ContentValues;)V
    :panorama_save_end
    .catch Ljava/lang/RuntimeException; {{:panorama_save_try .. :panorama_save_end}} :panorama_save_error

    const/4 v0, 0x1

    return v0

    :panorama_save_error
    move-exception v0

    const-string v1, "PictureProcessor"

    const-string v2, "Could not save the file-based image"

    invoke-static {{v1, v2, v0}}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    invoke-direct {{p0}}, {T}->cleanupFailedFileImage()V

    const/4 v0, 0x0

    return v0
.end method

.method private cleanupFailedFileImage()V
    .locals 3

    iget-object v0, p0, {T}->mPendingPanoramaImage:{H}

    if-eqz v0, :panorama_save_clear

    invoke-virtual {{v0}}, {H}->fail()V

    :panorama_save_clear
    iget-object v0, p0, {T}->this$0:{P}

    invoke-static {{v0}}, {P}->access$300({P}){E}

    move-result-object v0

    invoke-virtual {{v0}}, {E}->getLastContentData()Lcom/sec/android/app/camera/interfaces/Engine$ContentData;

    move-result-object v0

    check-cast v0, Lcom/sec/android/app/camera/engine/LastContentData;

    invoke-virtual {{v0}}, Lcom/sec/android/app/camera/engine/LastContentData;->getContentUriForWriting()Landroid/net/Uri;

    move-result-object v1

    iget-object v2, p0, {T}->mUri:Landroid/net/Uri;

    if-eqz v1, :panorama_save_failed

    invoke-virtual {{v1, v2}}, Landroid/net/Uri;->equals(Ljava/lang/Object;)Z

    move-result v1

    if-eqz v1, :panorama_save_failed

    invoke-virtual {{v0}}, Lcom/sec/android/app/camera/engine/LastContentData;->clear()V

    :panorama_save_failed
    return-void
.end method
'''
    task += f'''
.method public abandonFileImage()V
    .locals 2

    invoke-direct {{p0}}, {T}->cleanupFailedFileImage()V

    iget-object v0, p0, {T}->this$0:{P}

    invoke-static {{v0}}, {P}->access$300({P}){E}

    move-result-object v0

    new-instance v1, Lcom/sec/android/app/camera/engine/-$$Lambda$PictureProcessor$PictureSavingTask$TOgza_B_5Y6MXhQzDd5SnvXHe4s;

    invoke-direct {{v1, p0}}, Lcom/sec/android/app/camera/engine/-$$Lambda$PictureProcessor$PictureSavingTask$TOgza_B_5Y6MXhQzDd5SnvXHe4s;-><init>({T})V

    invoke-virtual {{v0, v1}}, {E}->postToUiThread(Ljava/lang/Runnable;)V

    return-void
.end method
'''
    old = _method(processor, '.method process(Ljava/lang/String;Ljava/lang/String;JLcom/sec/android/app/camera/interfaces/InternalEngine$PictureSavingType;)V')
    new = _once(old, '    const-string p0, "PictureProcessor"', f'''    iget-object v1, p0, {P}->mEngine:{E}

    invoke-virtual {{v1}}, {E}->cancelPendingPanoramaImage()V

    const-string p0, "PictureProcessor"''')
    call = '    invoke-virtual {v0, v9}, Ljava/util/concurrent/ThreadPoolExecutor;->execute(Ljava/lang/Runnable;)V'
    new = _once(new, call, f'''    :panorama_enqueue_try
{call}
    :panorama_enqueue_end
    .catch Ljava/util/concurrent/RejectedExecutionException; {{:panorama_enqueue_try .. :panorama_enqueue_end}} :panorama_enqueue_failed

    return-void

    :panorama_enqueue_failed
    move-exception v0

    invoke-virtual {{v9}}, {T}->abandonFileImage()V''')
    processor = processor.replace(old, new)

    # Write only after every original-layout assertion has succeeded.
    for path, text in ((engine_path, engine), (task_path, task), (request_path, request),
                       (processor_path, processor), (panorama_path, panorama)):
        path.write_text(text)
