import math
import os.path
import sys
import xml.etree.ElementTree
import datetime
import json
import shutil

from PySide6 import QtCore, QtGui, QtQml, QtQuick

# If running this on the main leica machine, dropbox folder should exist at ~/Dropbox (DGG Lab), e.g.
# "C:\Users\GGG-Leica-DM6M\Dropbox (DGG Lab)". Use this if it exists, otherwise just ~/leica_cv
USER_DIR = os.path.expanduser("~")
DROPBOX_ROOT = os.path.join(USER_DIR, "Dropbox (DGG Lab)")
ROOT = DROPBOX_ROOT if os.path.exists(DROPBOX_ROOT) else USER_DIR

CV_DATA_ROOT = os.path.join(ROOT, 'leica_cv', 'data')
COPIED_IMAGES = os.path.join(CV_DATA_ROOT, "copied_images")
ANNOTATIONS_DIR = os.path.join(CV_DATA_ROOT, "annotations")

print("Saving data to", CV_DATA_ROOT)

def add_incremented_suffix(path: str):
    path_stem, extension = os.path.splitext(path)
    i = 0
    while i < 999:
        path_candidate = f"{path_stem}_{i:03}{extension}"
        if not os.path.exists(path_candidate):
            return path_candidate
        i+=1
    raise RuntimeError("Exceeded 1k files with same base name")


def save_annotation(img_path, x1, y1, x2, y2, flake_type, quality):
    [os.makedirs(x, exist_ok=True) for x in [COPIED_IMAGES, ANNOTATIONS_DIR]]

    name, img_ext = os.path.splitext(os.path.basename(img_path))

    # Save copy of image
    copied_img_path = add_incremented_suffix(os.path.join(COPIED_IMAGES, name + img_ext))
    shutil.copyfile(img_path, copied_img_path)

    # Save metadata
    metadata_save_path = add_incremented_suffix(os.path.join(ANNOTATIONS_DIR, name + '.json'))
    d = {
        "timestamp": datetime.datetime.now().isoformat(),
        "original_img_path": img_path,
        "copied_img_path": copied_img_path,
        "top_left": [x1, y1],
        "bot_right": [x2, y2],
        "flake_type": flake_type,
        "flake_quality": quality
    }
    with open(metadata_save_path, 'w') as fout:
        json.dump(d, fout)

    print(f"Copied img and annotation data to {copied_img_path} and {metadata_save_path}")


class Histogram(QtQuick.QQuickPaintedItem):

    source_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nbins = 20
        self._reds = [0] * self._nbins
        self._greens = [0] * self._nbins
        self._blues = [0] * self._nbins

    @QtCore.Property(str, notify=source_changed)
    def source(self):
        return self._source

    @source.setter
    def source(self, source):
        self._source = source
        self._reds = [0] * self._nbins
        self._greens = [0] * self._nbins
        self._blues = [0] * self._nbins
        if len(source) == 0: return
        img = QtGui.QImage(source).convertToFormat(QtGui.QImage.Format_RGB32)
        bits = img.constBits()
        for i in range(img.width())[::img.width() // 20]:
            for j in range(img.height())[::img.height() // 20]:
                offset = 4 * (i * img.height() + j)
                self._reds[math.floor(bits[offset] / 256 * self._nbins)] += 1
                self._greens[math.floor(bits[offset + 1] / 256 * self._nbins)] += 1
                self._blues[math.floor(bits[offset + 2] / 256 * self._nbins)] += 1
        self.update()

    def paint(self, qp):
        max_sum = 1
        for r, g, b in zip(self._reds, self._blues, self._greens):
            max_sum = max(max_sum, r + g + b)
        w, h = self.width(), self.height()
        qp.setPen(QtGui.QColor(0, 0, 0, 255))
        qp.setBrush(QtGui.QColor(255, 255, 255, 128))
        qp.drawRect(0, 0, w - 1, h - 1)
        qp.setPen(QtGui.QColor(0, 0, 0, 0))
        for i, (r, g, b) in enumerate(zip(self._reds, self._blues, self._greens)):
            # Some fiddly bits.
            x = (w - 2) * i // self._nbins + 1
            rw = w // self._nbins
            rh = math.floor((h - 1) * r / max_sum)
            gh = math.floor((h - 1) * g / max_sum)
            bh = math.floor((h - 1) * b / max_sum)

            qp.setBrush(QtGui.QColor(255, 0, 0, 255))
            qp.drawRect(x, h - rh - 1, rw, rh)
            qp.setBrush(QtGui.QColor(0, 255, 0, 255))
            qp.drawRect(x, h - rh - gh - 1, rw, gh)
            qp.setBrush(QtGui.QColor(0, 0, 255, 255))
            qp.drawRect(x, h - rh - gh - bh - 1, rw, bh)


class Minimap(QtQuick.QQuickPaintedItem):

    loadedChanged = QtCore.Signal(bool)
    imagePathChanged = QtCore.Signal(str)
    totalWidthChanged = QtCore.Signal(float)
    totalHeightChanged = QtCore.Signal(float)
    imageWidthChanged = QtCore.Signal(float)
    imageHeightChanged = QtCore.Signal(float)
    positionXChanged = QtCore.Signal(float)
    positionYChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded = False
        self._field = {}
        self._tiles = []
        self._dim_x = {}
        self._dim_y = {}
        self._sel = 0
        self._min_x, self._min_y = float('inf'), float('inf')
        self._max_x, self._max_y = float('-inf'), float('-inf')
        self._timer = 0
        self._timer_sel = 0

    def _overlap(self, fx1, fy1, fx2, fy2):
        # How much do the specified tiles overlap in x and y?
        if (fx1, fy1) not in self._field: return 0, 0
        if (fx2, fy2) not in self._field: return 0, 0
        t1 = self._tiles[self._field[(fx1, fy1)]]
        t2 = self._tiles[self._field[(fx2, fy2)]]
        if t1['minipix'] is None: return 0, 0
        if t2['minipix'] is None: return 0, 0
        return (
            1 - abs(t1['pos_x'] - t2['pos_x']) / self._dim_x['len'],
            1 - abs(t1['pos_y'] - t2['pos_y']) / self._dim_y['len'])

    def paint(self, qp):
        w, h = self.width(), self.height()

        # Draw background. Will be covered up eventually.
        qp.setPen(QtGui.QColor(0, 0, 0, 0))
        qp.setBrush(QtGui.QColor(255, 255, 255, 128))
        qp.drawRect(0, 0, w - 1, h - 1)

        # Now draw rectangles and mini images.
        qp.setPen(QtGui.QColor(100, 100, 100))
        qp.setBrush(QtGui.QColor(0, 0, 0, 0))
        for tile in self._tiles:
            if tile['minipix'] is None:
                qp.drawRect(
                    (tile['pos_x'] - self._min_x) * self._scale,
                    (tile['pos_y'] - self._min_y) * self._scale,
                    self._dim_x['len'] * self._scale,
                    self._dim_y['len'] * self._scale)
            else:
                # Extra complicated because I want to truncate half of the
                # overlapped part of the images. Helps cut down on vignetting.
                fx, fy = tile['field_x'], tile['field_y']
                i_x = (tile['pos_x'] - self._min_x) * self._scale
                i_y = (tile['pos_y'] - self._min_y) * self._scale
                i_w = self._dim_x['len'] * self._scale
                i_h = self._dim_y['len'] * self._scale

                ovl_l, _ = self._overlap(fx, fy, fx - 1, fy)
                ovl_r, _ = self._overlap(fx, fy, fx + 1, fy)
                _, ovl_t = self._overlap(fx, fy, fx, fy - 1)
                _, ovl_b = self._overlap(fx, fy, fx, fy + 1)

                i_x += ovl_l * i_w / 2
                i_w -= ovl_l * i_w / 2 + ovl_r * i_w / 2
                i_y += ovl_t * i_h / 2
                i_h -= ovl_t * i_h / 2 + ovl_b * i_h / 2

                sx = 0
                sy = 0
                sw = tile['minipix'].width()
                sh = tile['minipix'].height()

                sx += ovl_l * sw / 2
                sw -= ovl_l * sw / 2 + ovl_r * sw / 2
                sy += ovl_t * sh / 2
                sh -= ovl_t * sh / 2 + ovl_b * sh / 2
                qp.drawPixmap(
                    math.floor(i_x),
                    math.floor(i_y),
                    math.ceil(i_w),
                    math.ceil(i_h),
                    tile['minipix'],
                    sx, sy, sw, sh)

        # Draw border.
        qp.setPen(QtGui.QColor(0, 0, 0, 255))
        qp.setBrush(QtGui.QColor(0, 0, 0, 0))
        qp.drawRect(0, 0, w - 1, h - 1)

        if len(self._tiles) == 0: return
        # Draw selected tile.
        tile = self._tiles[self._sel]
        qp.setPen(QtGui.QColor(255, 0, 0))
        qp.drawRect(
            (tile['pos_x'] - self._min_x) * self._scale,
            (tile['pos_y'] - self._min_y) * self._scale,
            self._dim_x['len'] * self._scale,
            self._dim_y['len'] * self._scale)

    @QtCore.Property(bool, notify=loadedChanged)
    def loaded(self):
        return self._loaded

    @QtCore.Property(str, notify=imagePathChanged)
    def imagePath(self):
        if len(self._tiles) == 0: return ''
        return self._tiles[self._sel]['path']

    @QtCore.Property(float, notify=totalWidthChanged)
    def totalWidth(self):
        if len(self._tiles) == 0: return 0
        return self._max_x - self._min_x + self._dim_x['len']

    @QtCore.Property(float, notify=positionXChanged)
    def positionX(self):
        if len(self._tiles) == 0: return 0
        return self._tiles[self._sel]['pos_x']

    @QtCore.Property(float, notify=positionYChanged)
    def positionY(self):
        if len(self._tiles) == 0: return 0
        return self._tiles[self._sel]['pos_y']

    @QtCore.Property(float, notify=totalHeightChanged)
    def totalHeight(self):
        if len(self._tiles) == 0: return 0
        return self._max_y - self._min_y + self._dim_y['len']

    @QtCore.Property(float, notify=imageWidthChanged)
    def imageWidth(self):
        if 'len' not in self._dim_x: return 0
        return self._dim_x['len']

    @QtCore.Property(float, notify=imageHeightChanged)
    def imageHeight(self):
        if 'len' not in self._dim_y: return 0
        return self._dim_y['len']

    @QtCore.Slot(QtCore.QUrl)
    def load(self, path):
        path = path.toLocalFile()
        prefix = os.path.basename(path)
        # TODO handle failure
        tree = xml.etree.ElementTree.parse(os.path.join(
            path,
            'leicametadata',
            f'{prefix}.xlif'))
        self._field = {}
        self._tiles = []
        self._dim_x = {}
        self._dim_y = {}
        self._min_x, self._min_y = float('inf'), float('inf')
        self._max_x, self._max_y = float('-inf'), float('-inf')
        self._sel = 0
        self._timer_sel = 0
        for child in tree.getroot()[0].find('Data')[0]:
            if child.get('Name') == 'TileScanInfo':
                for i, tile in enumerate(child.findall('Tile')):
                    fx, fy = int(tile.get('FieldX')), int(tile.get('FieldY'))
                    px, py = float(tile.get('PosX')), float(tile.get('PosY'))
                    self._min_x = min(self._min_x, px)
                    self._max_x = max(self._max_x, px)
                    self._min_y = min(self._min_y, py)
                    self._max_y = max(self._max_y, py)
                    self._field[(fx, fy)] = i
                    self._tiles.append({
                        'field_x': fx,
                        'field_y': fy,
                        'pos_x': px,
                        'pos_y': py,
                        'path': os.path.join(path, f'{prefix}--Stage{i:03}.jpg'),
                        'minipix': None,
                    })
            if child.tag == 'ImageDescription':
                for dim in child.find('Dimensions'):
                    if dim.get('DimID') == '1':
                        d = self._dim_x
                    elif dim.get('DimID') == '2':
                        d = self._dim_y
                    else:
                        continue
                    d['px'] = int(dim.get('NumberOfElements'))
                    d['len'] = float(dim.get('Length'))
                    d['unit'] = dim.get('Unit')
        t_w = self._max_x - self._min_x + self._dim_x['len']
        t_h = self._max_y - self._min_y + self._dim_y['len']
        self._scale = min(self.width() / t_w, self.height() / t_h)
        self.setWidth(t_w * self._scale)

        if self._dim_x['unit'] != 'm':
            print('X unit is not meters. You will have wrong scale readings!')
        if self._dim_y['unit'] != 'm':
            print('Y unit is not meters. You will have wrong scale readings!')

        if self._timer > 0:
            self.killTimer(self._timer)
        self._timer = self.startTimer(100)

        self._loaded = True
        self.imagePathChanged.emit(self.imagePath)
        self.positionXChanged.emit(self.positionX)
        self.positionYChanged.emit(self.positionY)
        self.totalWidthChanged.emit(self.totalWidth)
        self.totalHeightChanged.emit(self.totalHeight)
        self.imageWidthChanged.emit(self.imageWidth)
        self.imageHeightChanged.emit(self.imageHeight)
        self.loadedChanged.emit(self.loaded)
        self.update()

    def _load_up(self, sel):
        tile = self._tiles[sel]
        if tile['minipix'] is not None: return
        img = QtGui.QImage(tile['path'])
        pm = QtGui.QPixmap(img)
        sc = pm.scaledToWidth(100)
        tile['minipix'] = sc
        self.update()

    def timerEvent(self, e):
        while (self._timer_sel < len(self._tiles)
            and self._tiles[self._timer_sel]['minipix'] is not None):
            self._timer_sel += 1
        if self._timer_sel == len(self._tiles):
            self.killTimer(self._timer)
            return
        self._load_up(self._timer_sel)

    @QtCore.Slot(float, float)
    def clicked(self, mx, my):
        if len(self._tiles) == 0: return
        nearest_d = float('inf')
        px, py = mx / self._scale, my / self._scale
        fx, fy = 0, 0
        # PROBABLY TOO SLOW FOR BIG TILE SCANS!
        for tile in self._tiles:
            d = math.sqrt(
                (tile['pos_x'] - self._min_x + self._dim_x['len'] / 2 - px)**2 +
                (tile['pos_y'] - self._min_y + self._dim_y['len'] / 2 - py)**2)
            if d < nearest_d:
                nearest_d = d
                fx, fy = tile['field_x'], tile['field_y']
        if (fx, fy) not in self._field: return
        sel = self._field[(fx, fy)]
        self._sel = sel
        self._load_up(self._sel)
        self.imagePathChanged.emit(self.imagePath)
        self.positionXChanged.emit(self.positionX)
        self.positionYChanged.emit(self.positionY)
        self.update()

    @QtCore.Slot()
    def next(self):
        if len(self._tiles) == 0: return
        self._sel = min(self._sel + 1, len(self._tiles) - 1)
        self._load_up(self._sel)
        self.imagePathChanged.emit(self.imagePath)
        self.positionXChanged.emit(self.positionX)
        self.positionYChanged.emit(self.positionY)
        self.update()

    @QtCore.Slot(int, int)
    def move(self, dx, dy):
        if len(self._tiles) == 0: return
        fx, fy = self._tiles[self._sel]['field_x'], self._tiles[self._sel]['field_y']
        if (fx + dx, fy + dy) not in self._field: return
        self._sel = self._field[(fx + dx, fy + dy)]
        self._load_up(self._sel)
        self.imagePathChanged.emit(self.imagePath)
        self.positionXChanged.emit(self.positionX)
        self.positionYChanged.emit(self.positionY)
        self.update()

    @QtCore.Slot(str, str, QtGui.QImage, float, float, float, float, str, str)
    def capture(self, root, prefix, image, x1, y1, x2, y2, label, quality):
        save_annotation(self._tiles[self._sel]['path'], x1, y1, x2, y2, label, quality)

        root = QtCore.QUrl(root).toLocalFile()
        path = add_incremented_suffix(os.path.join(root, f'{prefix}_{label}{"_" + quality.replace(" ","") if quality else ""}.png'))
        image.save(path)


if __name__ == '__main__':
    app = QtGui.QGuiApplication(sys.argv)

    QtQml.qmlRegisterType(Minimap, 'wow', 1, 0, 'Minimap')
    QtQml.qmlRegisterType(Histogram, 'wow', 1, 0, 'Histogram')

    app.setOrganizationName('imv')
    app.setOrganizationDomain('imv')
    app.setApplicationName('imv')

    engine = QtQml.QQmlApplicationEngine()
    engine.quit.connect(app.quit)
    engine.load('main.qml')

    app.aboutToQuit.connect(engine.deleteLater)

    sys.exit(app.exec())
