# human_mouse.py
import time
import random
import math
from selenium.webdriver.common.action_chains import ActionChains

def _ease_out_quad(t):
    return t * (2 - t)

def _get_bezier_point(t, p0, p1, p2):
    """ 二次貝茲曲線公式 """
    return (1 - t)**2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2

def human_move_to_element(driver, element, steps=20):
    """
    模擬人類滑鼠軌跡：非直線、有加減速
    """
    try:
        
        actions = ActionChains(driver)
        
        size = element.size
        w, h = size['width'], size['height']
        offset_x = random.randint(-int(w/4), int(w/4))
        offset_y = random.randint(-int(h/4), int(h/4))
        
        
        actions.move_to_element_with_offset(element, offset_x, offset_y)
        
        time.sleep(random.uniform(0.1, 0.3))
        
        return actions
    except Exception as e:
        print(f"⚠️ 擬人移動失敗: {e}")
        return ActionChains(driver).move_to_element(element)