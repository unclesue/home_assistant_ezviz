"""Ezviz Entities"""
import logging
import json
import requests
from async_timeout import timeout
from aiohttp.client_exceptions import ClientConnectorError
import time

from homeassistant.components.switch import SwitchEntity

from .const import (
    COORDINATOR, 
    DOMAIN, 
    CONF_SWITCHS,
    SWITCH_TYPES,
    PRIVACY_PRESETS,
)

TIMEOUT_SECONDS=10
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add Switchentities from a config_entry."""      
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR] 
    haswitchs = config_entry.options.get(CONF_SWITCHS,["on_off"])
    switchs = []
    _LOGGER.debug(coordinator.data)   
    if coordinator.data.get("devicelistinfo"):
        devices = coordinator.data.get("devicelistinfo")
        evzizcameras = coordinator.data.get("cameralistinfo")
        _LOGGER.debug(devices)
        _LOGGER.debug(evzizcameras)
        if isinstance(devices, list):
            for device in devices:
                for devicechannel in evzizcameras:
                    if devicechannel["deviceSerial"] == device["deviceSerial"] and devicechannel["permission"] == -1:
                        switchtypes = {}
                        switchtypes["soundswitch"] = SWITCH_TYPES["soundswitch"]
                        if coordinator.data["capacity"][device["deviceSerial"]].get("support_privacy") == '1':
                            switchtypes["on_off"] = SWITCH_TYPES["on_off"]
                        # 云台隐私遮蔽（只要支持 PTZ 就加）
                        # if coordinator.data["capacity"][device["deviceSerial"]].get("ptz_preset") == '1':
                        #     switchtypes["privacy_preset"] = SWITCH_TYPES["privacy_preset"]
                        if coordinator.data["capacity"][device["deviceSerial"]].get("ptz_preset") == '1':
                            switchs.append(EzvizPrivacySwitch(hass, 'privacy_preset', coordinator, device["deviceSerial"], devicechannel["channelNo"]))
                        if coordinator.data["capacity"][device["deviceSerial"]].get("support_defence") == '1':
                            switchtypes["defence"] = SWITCH_TYPES["defence"]
                        switchtypes = {key: value for key, value in switchtypes.items() if value is not None}    
                        for swtich in switchtypes:
                            if swtich in haswitchs or swtich == "defence":
                                switchs.append(EzvizSwitch(hass, swtich, coordinator, device["deviceSerial"]))
                            # elif swtich == "privacy_preset":
                            #     switchs.append(EzvizSwitch(hass, swtich, coordinator, device["deviceSerial"]))
                # 设置侦测
                switchs.append(EzvizPrivacySwitch(hass, 'detect', coordinator, device["deviceSerial"], devicechannel["channelNo"]))
                
            async_add_entities(switchs, False)

class EzvizSwitch(SwitchEntity):
    _attr_has_entity_name = True
    def __init__(self, hass, kind, coordinator, deviceserial):
        """Initialize."""
        super().__init__()
        self.kind = kind
        self.coordinator = coordinator
        self._deviceserial = deviceserial
        self._state = None

        self._devicename = None
        self._deviceType = None
        self._deviceVersion = None
        
        for switchdata in self.coordinator.data["devicelistinfo"]:
            if switchdata["deviceSerial"] == self._deviceserial:
                self._devicename = switchdata["deviceName"]
                self._deviceType = switchdata["deviceType"]
                self._deviceVersion = switchdata["deviceVersion"]

                
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._deviceserial)},
            "name": self._devicename,
            "manufacturer": "Ezviz",
            "model": self._deviceType,
            "sw_version": self._deviceVersion,
        }
        self._attr_device_class = "switch"
        self._attr_entity_registry_enabled_default = True
        self._hass = hass
        self._name = SWITCH_TYPES[self.kind][1]
        self._turn_on_body = ""
        self._turn_off_body = ""
        self._change = True
        self._switchonoff = None
        
        self._listswitch = self.coordinator.data.get(self._deviceserial)
        
        if self.kind == "privacy_preset":
            # 云台预置位是“无状态 switch”
            self._is_on = False
            self._state = "off"
        else:
            self._switchonoff = self._listswitch[self.kind]
            self._is_on = self._switchonoff == 1
            self._state = "on" if self._is_on == True else "off"

   
    @property
    def name(self):
        """Return the name."""
        return f"{self._name}"

    @property
    def unique_id(self):
        return f"{DOMAIN}_switch_{self.kind}_{self._deviceserial}"

        
    @property
    def should_poll(self):
        """Return the polling requirement of the entity."""
        return False
        
    @property
    def extra_state_attributes(self):
        """Return device state attributes."""
        attrs = {}
        attrs["ezviz_accesstoken"] = self.coordinator.data["params"]["accessToken"]
        attrs["defence"] = self._listswitch["defence"]
        attrs["alarmSoundMode"] = self._listswitch["alarmSoundMode"]
        attrs["netAddress"] = self._listswitch["netAddress"]
        attrs["uptime"] = self._listswitch["updateTime"]
        attrs["querytime"] = self.coordinator.data["updatetime"]
        
        return attrs
        
    @property
    def icon(self):
        """Return the icon."""
        return SWITCH_TYPES[self.kind][2]

    @property
    def is_on(self):
        """Check if switch is on."""        
        return self._is_on

    async def async_turn_on(self, **kwargs):
        """Turn switch on."""
        self._is_on = True
        self._change = False
        await self._switch("on")
        self._switchonoff = "on"
        self.async_write_ha_state()


    async def async_turn_off(self, **kwargs):
        """Turn switch off."""
        self._is_on = False
        self._change = False
        await self._switch("off")
        self._switchonoff = "off"
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update entity."""
        #await self.coordinator.async_request_refresh()
        if self.kind == "privacy_preset":
            return  # 无状态，不从 coordinator 更新
        
        self._listswitch = self.coordinator.data.get(self._deviceserial)
        self._switchonoff = self._listswitch[self.kind]
                
        self._is_on = self._switchonoff == 1
        self._state = "on" if self._is_on == True else "off"
        
    def is_json(self, jsonstr):
        try:
            json.loads(jsonstr)
        except ValueError:
            return False
        return True

    # def sendHttpPost(self, url, data):
    #     try:            
    #         resp = requests.post(url, data = data, timeout=TIMEOUT_SECONDS)
    #         _LOGGER.debug(url)
    #         json_text = resp.text
    #         if self.is_json(json_text):
    #             resdata = json.loads(json_text)
    #         else:
    #             resdata = resp
    #         return resdata
    #     except Exception as e:
    #         _LOGGER.error("requst url:{url} Error:{err}".format(url=url,err=e))
    #         return None 

    def sendHttpPost(self, url, data, headers=None):
        try:
            resp = requests.post(
                url,
                data=data,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
            _LOGGER.debug("POST %s status=%s", url, resp.status_code)

            try:
                return resp.json()   # 永远返回 dict
            except ValueError:
                _LOGGER.error(
                    "Non-JSON response from %s: %s",
                    url,
                    resp.text,
                )
                return None
        except Exception as e:
            _LOGGER.error("request url:%s error:%s", url, e)
            return None

        
    async def _switch(self, action): 
        _LOGGER.debug(self.kind)
        if self.kind == "on_off":
            url = "https://open.ys7.com/api/lapp/device/scene/switch/set"
            
            ctrl = {"accessToken": self.coordinator.data["params"]["accessToken"],
                    "deviceSerial": self._deviceserial,               
                   }
            _LOGGER.debug(action)
            if action == "on":
                ctrl["enable"] = '0'
            elif action == "off":
                ctrl["enable"] = '1'
            else:
                ctrl["enable"]= None
                
        elif self.kind == "soundswitch":
            url = "https://open.ys7.com/api/lapp/camera/video/sound/set"
            
            ctrl = {"accessToken": self.coordinator.data["params"]["accessToken"],
                    "deviceSerial": self._deviceserial,               
                   }
            _LOGGER.debug(action)
            if action == "on":
                ctrl["enable"] = '1'
            elif action == "off":
                ctrl["enable"] = '0'
            else:
                ctrl["enable"]= None

        elif self.kind == "privacy_preset":
            url = "https://open.ys7.com/api/lapp/device/preset/move"
            
            ctrl = {"accessToken": self.coordinator.data["params"]["accessToken"],
                    "deviceSerial": self._deviceserial,
                    "channelNo": 1,
                    "index": 2 if action == "on" else 1             
                   }
            _LOGGER.debug(action)
            if action == "on":
                ctrl["enable"] = '1'
            elif action == "off":
                ctrl["enable"] = '0'
            else:
                ctrl["enable"]= None
                
        elif self.kind == "defence":
            url = "https://open.ys7.com/api/lapp/device/defence/set"
            
            ctrl = {"accessToken": self.coordinator.data["params"]["accessToken"],
                    "deviceSerial": self._deviceserial,
                   }
            _LOGGER.debug(action)
            if action == "on":
                ctrl["isDefence"] = '1'
                _LOGGER.debug(ctrl)
            elif action == "off":                
                ctrl["isDefence"] = '0'
                _LOGGER.debug(ctrl)
            else:
                ctrl["isDefence"]= None
                _LOGGER.debug(ctrl)  
        else:
        
            actionstr = "1" if action == "on" else "0"            
            url = "https://open.ys7.com/api/deviceconfig/v3/devices/" + self._deviceserial + "/0/" + actionstr + "/" + SWITCH_TYPES[self.kind][3] + "/switchStatus"            
            ctrl = {"accessToken": self.coordinator.data["params"]["accessToken"],
                    "deviceSerial": self._deviceserial,
                   } 
            _LOGGER.debug(ctrl)  
        
        try:
            async with timeout(10): 
                resdata = await self._hass.async_add_executor_job(self.sendHttpPost, url, ctrl)
        except (
            ClientConnectorError
        ) as error:
            raise UpdateFailed(error)
        _LOGGER.debug("Requests remaining: %s, ctrl: %s", url, ctrl)
        _LOGGER.debug(resdata)
  

class EzvizPrivacySwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hass, kind, coordinator, deviceserial, channelno):
        self._hass = hass
        self.kind = kind
        self.coordinator = coordinator
        self._deviceserial = deviceserial
        self._channelno = channelno

        self._devicename = None
        self._deviceType = None
        self._deviceVersion = None
        
        for switchdata in self.coordinator.data["devicelistinfo"]:
            if switchdata["deviceSerial"] == self._deviceserial:
                self._devicename = switchdata["deviceName"]
                self._deviceType = switchdata["deviceType"]
                self._deviceVersion = switchdata["deviceVersion"]
                
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._deviceserial)},
            "name": self._devicename,
            "manufacturer": "Ezviz",
            "model": self._deviceType,
            "sw_version": self._deviceVersion,
        }

        self._is_on = True if SWITCH_TYPES[self.kind][3] else False  # HA 内部状态
        self._attr_icon = SWITCH_TYPES[self.kind][2]
        self._attr_name = SWITCH_TYPES[self.kind][1]
        self._attr_unique_id = f"{DOMAIN}_switch_{self.kind}_{self._deviceserial}"

    @property
    def is_on(self):
        return self.coordinator.data.get(self._deviceserial, {}).get("humanDetect", 0) if self.kind == "detect" else self._is_on

    def sendHttpPost(self, url, data, headers=None):
        try:
            resp = requests.post(
                url,
                data=data,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
            _LOGGER.debug("POST %s status=%s", url, resp.status_code)

            try:
                return resp.json()   # 永远返回 dict
            except ValueError:
                _LOGGER.error(
                    "Non-JSON response from %s: %s",
                    url,
                    resp.text,
                )
                return None
        except Exception as e:
            _LOGGER.error("request url:%s error:%s", url, e)
            return None

    async def async_turn_on(self, **kwargs):
        await self._switch("on")
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._switch("off")
        self._is_on = False
        self.async_write_ha_state()

    async def _switch(self, state: str):
        if self.kind == "privacy_preset":
            preset = PRIVACY_PRESETS[state]
            url = "https://open.ys7.com/api/lapp/device/preset/move"
            ctrl = {
                "accessToken": self.coordinator.data["params"]["accessToken"],
                "deviceSerial": self._deviceserial,
                "channelNo": self._channelno,
                "index": preset,
            }
            await self._hass.async_add_executor_job(requests.post, url, ctrl)

        elif self.kind == "detect":
            url = "https://open.ys7.com/api/v3/device/detect/switch/set"
            ctrl = {
                "accessToken": self.coordinator.data["params"]["accessToken"],
                "deviceSerial": self._deviceserial,
                "type": 8 if state == "on" else 0,
            }
            # response = await self._hass.async_add_executor_job(requests.post, url, ctrl)
            response = await self._hass.async_add_executor_job(
                self.sendHttpPost, url, ctrl
            )

            if response and response.get("code") == "200":
                device_data = self.coordinator.data.setdefault(self._deviceserial, {})
                device_data["humanDetect"] = 1 if state == "on" else 0
                device_data["_humanDetect_local_ts"] = time.time()
            else:
                _LOGGER.error(
                    "Set humanDetect failed for %s: %s",
                    self._deviceserial,
                    response,
                )

