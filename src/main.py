# 高分屏：不再关闭 Qt 高分缩放（旧补丁只治标，反而导致高分屏文字发糊）。
# 坐标与边缘拖拽已由 app.py 的 PassThrough 缩放策略 + nativeEvent DPR 换算处理。

from qbotmanager.app import main

if __name__ == "__main__":
    main()
