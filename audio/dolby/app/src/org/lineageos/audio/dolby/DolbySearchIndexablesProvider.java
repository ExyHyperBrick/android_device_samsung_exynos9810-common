/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.dolby;

import static android.provider.SearchIndexablesContract.COLUMN_INDEX_XML_RES_ICON_RESID;
import static android.provider.SearchIndexablesContract.COLUMN_INDEX_XML_RES_INTENT_ACTION;
import static android.provider.SearchIndexablesContract.COLUMN_INDEX_XML_RES_INTENT_TARGET_CLASS;
import static android.provider.SearchIndexablesContract.COLUMN_INDEX_XML_RES_INTENT_TARGET_PACKAGE;
import static android.provider.SearchIndexablesContract.COLUMN_INDEX_XML_RES_RANK;
import static android.provider.SearchIndexablesContract.COLUMN_INDEX_XML_RES_RESID;
import static android.provider.SearchIndexablesContract.INDEXABLES_RAW_COLUMNS;
import static android.provider.SearchIndexablesContract.INDEXABLES_XML_RES_COLUMNS;
import static android.provider.SearchIndexablesContract.NON_INDEXABLES_KEYS_COLUMNS;

import android.database.Cursor;
import android.database.MatrixCursor;
import android.os.UserHandle;
import android.provider.SearchIndexablesProvider;

public final class DolbySearchIndexablesProvider extends SearchIndexablesProvider {
    @Override
    public boolean onCreate() { return true; }

    @Override
    public Cursor queryXmlResources(String[] projection) {
        MatrixCursor cursor = new MatrixCursor(INDEXABLES_XML_RES_COLUMNS);
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) return cursor;
        Object[] row = new Object[INDEXABLES_XML_RES_COLUMNS.length];
        row[COLUMN_INDEX_XML_RES_RANK] = 1;
        row[COLUMN_INDEX_XML_RES_RESID] = R.xml.dolby_settings;
        row[COLUMN_INDEX_XML_RES_ICON_RESID] = R.drawable.ic_dolby;
        row[COLUMN_INDEX_XML_RES_INTENT_ACTION] = "com.android.settings.action.EXTRA_SETTINGS";
        row[COLUMN_INDEX_XML_RES_INTENT_TARGET_PACKAGE] = getContext().getPackageName();
        row[COLUMN_INDEX_XML_RES_INTENT_TARGET_CLASS] = DolbyActivity.class.getName();
        cursor.addRow(row);
        return cursor;
    }

    @Override
    public Cursor queryRawData(String[] projection) {
        return new MatrixCursor(INDEXABLES_RAW_COLUMNS);
    }

    @Override
    public Cursor queryNonIndexableKeys(String[] projection) {
        MatrixCursor cursor = new MatrixCursor(NON_INDEXABLES_KEYS_COLUMNS);
        cursor.addRow(new Object[] {"dolby_intro"});
        cursor.addRow(new Object[] {"dolby_status"});
        cursor.addRow(new Object[] {"dolby_retry"});
        return cursor;
    }
}
