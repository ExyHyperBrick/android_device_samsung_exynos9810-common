/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.os.storage.StorageVolume;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;

/** Uses the camera's own preferences, including when opened from device settings. */
public final class StorageSettingsActivity extends Activity {
    private AlertDialog mDialog;
    private Spinner mVolume;
    private EditText mFolder;
    private final ArrayList<String> mVolumeNames = new ArrayList<>();

    private String text(String name) {
        return getString(getResources().getIdentifier(name, "string", getPackageName()));
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        StorageCompat.initialize(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (24 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding / 2, padding, padding / 2);
        TextView description = new TextView(this);
        description.setText(text("lineage_storage_description"));
        layout.addView(description);
        ArrayList<String> labels = new ArrayList<>();
        labels.add(text("lineage_storage_internal"));
        mVolumeNames.add(MediaStore.VOLUME_EXTERNAL_PRIMARY);
        for (StorageVolume volume : StorageCompat.removableVolumes(this)) {
            labels.add(volume.getDescription(this));
            mVolumeNames.add(volume.getMediaStoreVolumeName());
        }
        mVolume = new Spinner(this);
        mVolume.setContentDescription(text("lineage_storage_volume"));
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        mVolume.setAdapter(adapter);
        String selected = state == null ? StorageCompat.selectedVolumeName()
                : state.getString("volume", MediaStore.VOLUME_EXTERNAL_PRIMARY);
        int index = mVolumeNames.indexOf(selected);
        mVolume.setSelection(Math.max(0, index));
        layout.addView(mVolume, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        if (index < 0) {
            TextView unavailable = new TextView(this);
            unavailable.setText(text("lineage_storage_unavailable"));
            layout.addView(unavailable);
        }
        mFolder = new EditText(this);
        mFolder.setSingleLine(true);
        mFolder.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        mFolder.setHint(text("lineage_storage_folder"));
        mFolder.setContentDescription(text("lineage_storage_folder"));
        mFolder.setText(state == null ? StorageCompat.folder() : state.getString("folder"));
        layout.addView(mFolder);
        mDialog = new AlertDialog.Builder(this)
                .setTitle(text("lineage_storage_title"))
                .setView(layout)
                .setPositiveButton(android.R.string.ok, null)
                .setNegativeButton(android.R.string.cancel, (button, which) -> finish())
                .setOnCancelListener(button -> finish())
                .create();
        final AlertDialog dialog = mDialog;
        dialog.setOnShowListener(button -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(view -> {
                    try {
                        if (!StorageCompat.save(mVolumeNames.get(mVolume.getSelectedItemPosition()),
                                mFolder.getText().toString())) {
                            Toast.makeText(this, text("lineage_storage_failed"),
                                    Toast.LENGTH_LONG).show();
                            return;
                        }
                        finish();
                    } catch (IllegalArgumentException error) {
                        mFolder.setError(text("lineage_storage_invalid"));
                    }
                }));
        dialog.show();
    }

    @Override protected void onDestroy() {
        if (mDialog != null) {
            mDialog.setOnCancelListener(null);
            mDialog.dismiss();
            mDialog = null;
        }
        super.onDestroy();
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putString("volume", mVolumeNames.get(mVolume.getSelectedItemPosition()));
        state.putString("folder", mFolder.getText().toString());
        super.onSaveInstanceState(state);
    }
}
