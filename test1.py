import re

pattern_timeout_Gizmo = r"Gizmo took (\d+)(?=ms)"
test_string = "Gizmo took 9088ms"
matches = re.findall(pattern_timeout_Gizmo, test_string)
print(matches)  # 输出: ['9088']