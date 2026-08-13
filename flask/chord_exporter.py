from fractions import Fraction
import os
import tempfile
from pathlib import Path

from music21 import stream, meter, note, chord as m21_chord, metadata, harmony, tempo
from PIL import Image, ImageDraw, ImageFont

from chordutils import fix_chord_label


class ChordExporter:
    def write_midi_and_musicxml(self, chord_data, file_repr):
        score = stream.Score(metadata=metadata.Metadata(title="Generated Chords", composer="Chord Conversion Script"))
        part = stream.Part()
        bpm = float(chord_data.bpm or 120)
        part.append(tempo.MetronomeMark(number=bpm))
        time_signature = f"{chord_data.meter_signature}/4" if chord_data.meter_signature else "4/4"
        part.append(meter.TimeSignature(time_signature))
        chords = chord_data.get_chords()
        chord_offsets = [
            self._seconds_to_quarter_length(timestamp, bpm)
            for timestamp, _ in chords
        ]
        for index, (timestamp, chord_label) in enumerate(chords):
            quarter_length = self._duration_quarter_length(chord_offsets, index, bpm)
            if index == 0 and timestamp > 0:
                part.append(note.Rest(quarterLength=chord_offsets[index]))
            try:
                fixed_chord_label = fix_chord_label(chord_label)
                chord_symbol = harmony.ChordSymbol(fixed_chord_label)
                chord_notes = m21_chord.Chord([p for p in chord_symbol.pitches], quarterLength=quarter_length)
                part.append(chord_notes)
            except Exception:
                part.append(note.Rest(quarterLength=quarter_length))
        score.append(part)
        self.__atomic_score_write(score, "musicxml", file_repr.get("xml"))
        print(f"MusicXML file saved: {file_repr.get('xml')}")
        self.__atomic_score_write(score, "midi", file_repr.get("mid"))
        print(f"MIDI file saved: {file_repr.get('mid')}")
        del score

    @staticmethod
    def __atomic_score_write(score, output_format, destination_path):
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.export-",
            suffix=destination.suffix,
            dir=destination.parent,
        )
        os.close(descriptor)
        os.unlink(temporary_name)
        try:
            score.write(output_format, fp=temporary_name)
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def _duration_quarter_length(self, chord_offsets, index, bpm):
        if index + 1 < len(chord_offsets):
            duration = chord_offsets[index + 1] - chord_offsets[index]
            if duration > 0:
                return duration
        return self._seconds_to_quarter_length(60.0 / bpm, bpm)

    def _seconds_to_quarter_length(self, seconds, bpm):
        raw_quarter_length = max(float(seconds) * bpm / 60.0, 1.0 / 64.0)
        return Fraction(max(1, round(raw_quarter_length * 16)), 16)

    def write_png(self, chord_data, file_repr, output_filename="chord_chart.png"):
        output_filepath = file_repr.get(output_filename)
        cell_width, cell_height, font_size, padding = 100, 100, 36, 10
        columns = 8
        chords = chord_data.get_chords()
        rows = (len(chords) // columns) + 1
        img = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()
        for idx, (timestamp, chord_label) in enumerate(chords):
            col, row = idx % columns, idx // columns
            x, y = col * cell_width + padding, row * cell_height + padding
            draw.rectangle([col * cell_width, row * cell_height, (col + 1) * cell_width, (row + 1) * cell_height], outline="black", width=2)
            bbox = draw.textbbox((0, 0), chord_label, font=font)
            text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x + (cell_width - text_width) / 2, y + (cell_height - text_height) / 2), chord_label, fill="black", font=font)
        img.save(output_filepath)
        print(f"Chord chart saved as: {output_filepath}")
