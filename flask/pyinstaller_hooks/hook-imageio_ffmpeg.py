"""Keep imageio-ffmpeg's optional wheel executable out of ChordFlask builds.

ChordFlask sets ``IMAGEIO_FFMPEG_EXE`` to the target system executable before
MoviePy or ImageIO performs media I/O, so neither the wheel data directory nor
its importlib-resources helper package belongs in the standalone artifact.
"""

datas = []
hiddenimports = []
