import QtQuick
import QtMultimedia

Item {
    id: root
    objectName: "root"
    property int cornerRadius: 14
    // 渲染缩放：QQuickWidget 按半分辨率离屏渲染，再放大铺满窗口。
    // 背景视频是暗色动态氛围，半分辨率视觉差异极小，但 GPU/CPU 合成开销降到 1/4。
    property real renderScale: 1
    transformOrigin: Item.TopLeft
    scale: root.renderScale

    MediaPlayer {
        id: mp
        objectName: "mp"
        videoOutput: video
        loops: MediaPlayer.Infinite
        onErrorOccurred: root.errorHappened(error, errorString)
    }

    VideoOutput {
        id: video
        objectName: "video"
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    signal errorHappened(int code, string msg)
}
