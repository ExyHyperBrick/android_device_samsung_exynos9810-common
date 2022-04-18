/*
 * Copyright (C) 2022 The LineageOS Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef _BDROID_BUILDCFG_H
#define _BDROID_BUILDCFG_H

#pragma push_macro("PROPERTY_VALUE_MAX")

#include <cutils/properties.h>
#include <string.h>

static inline const char* BtmGetDefaultName()
{
    char product_device[PROPERTY_VALUE_MAX];
    property_get("ro.product.device", product_device, "");

    if (strstr(product_device, "starlte"))
        return "Galaxy S9";
    if (strstr(product_device, "star2lte"))
        return "Galaxy S9+";
    if (strstr(product_device, "crownlte"))
        return "Galaxy Note 9";

    // Fallback to Default
    return "Samsung Galaxy";
}

#define BTM_DEF_LOCAL_NAME BtmGetDefaultName()

#define BLE_VND_INCLUDED TRUE

#define BTA_AV_SINK_INCLUDED TRUE

#pragma pop_macro("PROPERTY_VALUE_MAX")

#endif
