# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Replace Samsung's private-volume discovery and storage spinner."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

A = '{http://schemas.android.com/apk/res/android}'
HELPER = 'Lorg/lineageos/camera/compat/StorageCompat;'
STOCK = 'Lcom/sec/android/app/camera/util/StorageUtils;'
ACTIVITY = 'org.lineageos.camera.compat.StorageSettingsActivity'
PERMISSION = 'com.sec.android.app.camera.permission.CONFIGURE_STORAGE'


def method(path, signature, body):
    text = path.read_text()
    pattern = re.compile(r'(?m)^\.method ' + re.escape(signature)
                         + r'\n.*?^\.end method$', re.S)
    if len(pattern.findall(text)) != 1:
        raise ValueError('Unexpected camera storage method: ' + signature)
    path.write_text(pattern.sub(lambda _: '.method ' + signature + '\n' + body
                               + '\n.end method', text, count=1))


def patch_storage(decoded):
    decoded = Path(decoded)
    classes = decoded / 'smali_classes2/com/sec/android/app/camera'
    app = decoded / 'smali/com/sec/android/app/camera/CameraApplication.smali'
    text = app.read_text()
    anchor = '.method public onCreate()V\n    .locals 5\n'
    if text.count(anchor) != 1:
        raise ValueError('Unexpected camera Application initialization')
    app.write_text(text.replace(anchor, anchor + '\n    invoke-static {p0}, '
            + HELPER + '->initialize(Landroid/content/Context;)V\n', 1))
    method(classes / 'setting/CameraSettingsImpl.smali', 'public getStorage()I', f'''    .locals 1
    invoke-static {{}}, {HELPER}->getStorage()I
    move-result v0
    return v0''')
    method(classes / 'util/ImageUtils.smali',
           'public static getImageSavingDir(I)Ljava/lang/String;', f'''    .locals 1
    invoke-static {{p0}}, {HELPER}->imageSavingDir(I)Ljava/lang/String;
    move-result-object v0
    return-object v0''')
    storage = classes / 'util/StorageUtils.smali'
    method(storage, 'public static getContentUri(Landroid/net/Uri;I)Landroid/net/Uri;', f'''    .locals 1
    invoke-static {{p0, p1}}, {HELPER}->collection(Landroid/net/Uri;I)Landroid/net/Uri;
    move-result-object v0
    return-object v0''')
    method(storage, 'public static setExternalSDStorageVolume(Landroid/content/Context;)V', f'''    .locals 3
    new-instance v0, Ljava/util/concurrent/CountDownLatch;
    const/4 v1, 0x1
    invoke-direct {{v0, v1}}, Ljava/util/concurrent/CountDownLatch;-><init>(I)V
    sput-object v0, {STOCK}->mStorageLatch:Ljava/util/concurrent/CountDownLatch;
    invoke-static {{}}, {STOCK}->clearExternalSDStoragePath()V
    const/4 v1, 0x0
    sput-object v1, {STOCK}->mSdStorageVolumeFsUuid:Ljava/lang/String;
    :try_start
    invoke-static {{p0}}, {HELPER}->firstRemovableVolume(Landroid/content/Context;)Landroid/os/storage/StorageVolume;
    move-result-object v1
    if-eqz v1, :done
    invoke-virtual {{v1}}, Landroid/os/storage/StorageVolume;->getDirectory()Ljava/io/File;
    move-result-object v2
    invoke-virtual {{v2}}, Ljava/io/File;->getPath()Ljava/lang/String;
    move-result-object v2
    sput-object v2, {STOCK}->mSdStorageVolumePath:Ljava/lang/String;
    sput-object v2, {STOCK}->mSdStorageVolumeInternalPath:Ljava/lang/String;
    invoke-virtual {{v1}}, Landroid/os/storage/StorageVolume;->getMediaStoreVolumeName()Ljava/lang/String;
    move-result-object v1
    sput-object v1, {STOCK}->mSdStorageVolumeFsUuid:Ljava/lang/String;
    :try_end
    .catchall {{:try_start .. :try_end}} :failed
    :done
    invoke-virtual {{v0}}, Ljava/util/concurrent/CountDownLatch;->countDown()V
    return-void
    :failed
    move-exception v1
    invoke-virtual {{v0}}, Ljava/util/concurrent/CountDownLatch;->countDown()V
    throw v1''')

    method(classes / 'util/RecordingUtil.smali',
           'public static createTempVideoFilePath(I)Ljava/lang/String;', '''    .locals 1
    invoke-static {p0}, Lcom/sec/android/app/camera/util/RecordingUtil;->createVideoDirectory(I)Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :done
    invoke-static {v0}, Lorg/lineageos/camera/compat/MediaStoreCompat;->pendingVideoPath(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    :done
    return-object v0''')

    # Ordinary video records to a native file before the pending row is created.
    # Its final in-place rename must update that same row, unlike URI-written JPEGs.
    recording = classes / 'engine/RecordingManagerImpl.smali'
    text = recording.read_text()
    for before, after in (
            ('->insertPending(', '->insertPendingVideo('),
            ('->publish(', '->publishVideo(')):
        target = 'Lorg/lineageos/camera/compat/MediaStoreCompat;' + before
        if text.count(target) != 1:
            raise ValueError('Unexpected recording media transaction: ' + before)
        text = text.replace(target, 'Lorg/lineageos/camera/compat/MediaStoreCompat;' + after)
    recording.write_text(text)

    # A plain preference launches the real editor. Its own key avoids the
    # stock removable-card-only visibility and spinner/value listeners.
    path = decoded / 'res/xml/setting.xml'
    tree = ET.parse(path)
    matches = [node for node in tree.iter()
               if node.get(A + 'key') == '@string/key_storage']
    if len(matches) != 1:
        raise ValueError('Unexpected Samsung storage preference')
    row = matches[0]
    row.tag = 'androidx.preference.Preference'
    row.attrib.clear()
    row.set(A + 'key', 'lineage_storage')
    row.set(A + 'title', '@string/lineage_storage_title')
    row.set(A + 'summary', '@string/lineage_storage_summary')
    ET.SubElement(row, 'intent', {A + 'targetPackage': 'com.sec.android.app.camera',
                                 A + 'targetClass': ACTIVITY})
    tree.write(path, encoding='utf-8', xml_declaration=True)
    strings = {
        'lineage_storage_title': 'Save location',
        'lineage_storage_summary': 'Choose internal storage, a memory card, and a folder under DCIM',
        'lineage_storage_description': 'Photos and videos are saved under DCIM. Enter a folder such as Camera or Camera/Trips. Recording modes that require internal storage keep using internal storage.',
        'lineage_storage_internal': 'Internal storage',
        'lineage_storage_volume': 'Storage volume',
        'lineage_storage_folder': 'Folder under DCIM',
        'lineage_storage_unavailable': 'The saved memory card is unavailable. Captures use internal storage until that card returns. Saving these settings selects the volume shown above.',
        'lineage_storage_failed': 'Could not save the storage settings',
        'lineage_storage_invalid': 'Choose an available volume and a folder under DCIM. Hidden folders, empty names, and reserved characters are not supported.',
    }
    resources = ET.Element('resources')
    for name, value in strings.items():
        ET.SubElement(resources, 'string', {'name': name}).text = value
    ET.ElementTree(resources).write(decoded / 'res/values/lineage_storage.xml',
                                    encoding='utf-8', xml_declaration=True)


def add_storage_activity(root, application):
    ET.SubElement(root, 'permission', {A + 'name': PERMISSION,
                                     A + 'protectionLevel': 'signature'})
    ET.SubElement(application, 'activity', {A + 'name': ACTIVITY,
        A + 'exported': 'true', A + 'permission': PERMISSION,
        A + 'theme': '@android:style/Theme.Material.NoActionBar'})
