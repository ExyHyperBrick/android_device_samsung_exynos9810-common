/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.content.Context;
import android.util.AttributeSet;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewParent;
import android.widget.FrameLayout;
import android.widget.SeekBar;

/** Keeps a native seek bar's drawing, touch and accessibility coordinates aligned. */
public final class VerticalSeekBar extends FrameLayout {
    private final SeekBar mSeekBar;

    public VerticalSeekBar(Context context, AttributeSet attrs) {
        super(context, attrs);
        setClipChildren(false);
        setClipToPadding(false);
        setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        mSeekBar = new SeekBar(context) {
            @Override
            public boolean onKeyDown(int keyCode, KeyEvent event) {
                if (keyCode == KeyEvent.KEYCODE_DPAD_UP) {
                    return super.onKeyDown(KeyEvent.KEYCODE_DPAD_RIGHT, event);
                }
                if (keyCode == KeyEvent.KEYCODE_DPAD_DOWN) {
                    return super.onKeyDown(KeyEvent.KEYCODE_DPAD_LEFT, event);
                }
                // Leave horizontal keys available for focus navigation between bands.
                if (keyCode == KeyEvent.KEYCODE_DPAD_LEFT
                        || keyCode == KeyEvent.KEYCODE_DPAD_RIGHT) return false;
                return super.onKeyDown(keyCode, event);
            }
        };
        mSeekBar.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        mSeekBar.setRotation(-90);
        mSeekBar.setMin(-12);
        mSeekBar.setMax(12);
        mSeekBar.setKeyProgressIncrement(1);
        addView(mSeekBar);
    }

    public SeekBar getSeekBar() {
        return mSeekBar;
    }

    @Override
    protected void onMeasure(int widthSpec, int heightSpec) {
        float density = getResources().getDisplayMetrics().density;
        int width = resolveSize(Math.round(48 * density), widthSpec);
        int height = resolveSize(Math.round(200 * density), heightSpec);
        setMeasuredDimension(width, height);
        mSeekBar.measure(MeasureSpec.makeMeasureSpec(height, MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(width, MeasureSpec.EXACTLY));
    }

    @Override
    protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        int width = right - left;
        int height = bottom - top;
        int childLeft = (width - height) / 2;
        int childTop = (height - width) / 2;
        mSeekBar.layout(childLeft, childTop, childLeft + height, childTop + width);
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        ViewParent parent = getParent();
        // The surrounding Settings list also scrolls vertically.
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN && isEnabled() && parent != null) {
            parent.requestDisallowInterceptTouchEvent(true);
        }
        boolean handled = super.dispatchTouchEvent(event);
        if (parent != null && (event.getActionMasked() == MotionEvent.ACTION_UP
                || event.getActionMasked() == MotionEvent.ACTION_CANCEL)) {
            parent.requestDisallowInterceptTouchEvent(false);
        }
        return handled;
    }
}
