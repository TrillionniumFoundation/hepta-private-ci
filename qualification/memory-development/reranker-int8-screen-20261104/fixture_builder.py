"""Original fictional engineering inputs; no relevance labels or external data."""
import json
from pathlib import Path

CASES = [
 ("short", "Where does the Luma lantern club keep its blue lanterns?", [
  "The Luma lantern club keeps blue lanterns in the east cupboard beside a copper bell. A paper moon marks that cupboard.",
  "The Luma lantern club stores amber lanterns under the west bench. Blue ribbons hang on the entrance rail during rehearsal.",
  "At the Mira kite workshop, blue lanterns decorate the ceiling. Its folded kites stay in a wide green chest.",
  "The Luma lantern club moved its guest book to the east cupboard. Lantern storage is not described on this notice."]),
 ("short", "When does the imaginary reed ferry leave Pebble Quay?", [
  "The reed ferry at Pebble Quay leaves after the third silver chime. Passengers wait by the painted wooden fish.",
  "Pebble Quay hosts a reed market before the first silver chime. The market has no timetable for the ferry.",
  "The ferry at Willow Quay leaves after the second copper chime. Its boarding post carries a violet cloth flag.",
  "Pebble Quay closes its ticket desk at dusk. A notice says the reed ferry timetable will be displayed inside tomorrow."]),
 ("short", "Which badge identifies a keeper of the Neri seed vault?", [
  "A keeper of the Neri seed vault wears a triangular amber badge. Visiting storytellers receive small round silver badges.",
  "The Neri seed vault labels barley jars with amber triangles. Staff badges are not listed in this inventory booklet.",
  "Keepers of the Vela seed vault wear a square violet badge. Their visitors carry braided cords instead of badges.",
  "Neri vault visitors collect a triangular amber badge at the outer desk. This fictional notice describes visitors rather than keepers."]),
 ("short", "How is the glass orchard gate opened in the story?", [
  "The glass orchard gate opens when someone turns the ivory wheel twice. A quiet bell then rings above the arch.",
  "The glass orchard gate opens when someone turns the ivory wheel twice. A quiet bell then rings above the arch.",
  "The glass orchard gate closes when the wooden lever is lowered. This notice does not describe the gate opening action.",
  "The copper orchard gate opens with one pull of a red cord. Its outer fence is painted with small stars."]),
 ("medium", "What material covers the roof of the fictional Brindle reading hut?", [
  "The Brindle reading hut has a roof covered with woven silver reeds. Smooth pine panels form its floor and entrance door.",
  "The Brindle reading hut has woven silver curtains by its windows. The roof material is not named in the caretaker note.",
  "The nearby Fenn reading hut uses blue clay tiles on its roof. Its shelves are assembled from pale pine boards.",
  "An old drawing proposes copper sheets for the Brindle reading hut roof. The drawing is labeled an unbuilt alternative design."]),
 ("medium", "Where should a borrowed star compass be returned in Orin village?", [
  "Borrowed star compasses in Orin village go back to the north window of the clock house. An attendant counts each return.",
  "Orin village lends paper maps from the south window of the clock house. Borrowed star compasses are not mentioned here.",
  "In Tavi village, borrowed star compasses are returned to the mill porch. A green tray there holds their cloth covers.",
  "Orin village displays an antique star compass at the north window of the museum. The display cannot accept borrowed objects."]),
 ("medium", "What signal begins the toy cloud parade at Hallow Meadow?", [
  "The toy cloud parade at Hallow Meadow begins with three soft drum taps. The cloud carriers then follow the yellow path.",
  "The toy cloud parade at Hallow Meadow ends with three soft drum taps. Its starting signal is omitted from this leaflet.",
  "At Coral Meadow the toy cloud parade begins when a wooden whistle sounds. Two lantern bearers lead the first cloud.",
  "The rehearsal at Hallow Meadow starts with one loud clap. The official toy cloud parade uses a separate written signal plan."]),
 ("medium", "Which drawer holds the violet ink at the Sora stamp desk?", [
  "The Sora stamp desk keeps violet ink in the second drawer. The drawer has a brass handle shaped like a leaf.",
  "The Sora stamp desk keeps violet ink in the second drawer. The drawer has a brass handle shaped like a leaf.",
  "The Sora stamp desk keeps green ink in the fourth drawer. A violet ribbon marks the cupboard containing blank paper.",
  "The Mena stamp desk keeps violet ink in the lowest drawer. Its second drawer contains only small wooden letter stamps."]),
 ("long", "Why is the fictional silver bridge closed during the moss festival?", [
  "The silver bridge closes during the moss festival so painted floats can be assembled on its deck. Walkers use the eastern footpath.",
  "The silver bridge stays open during the moss festival while painted floats gather at the mill. The eastern footpath is closed.",
  "The bronze bridge closes during the reed festival for railing repairs. Its visitors are directed toward the western stepping stones.",
  "A draft plan suggests closing the silver bridge during the moss festival because of lantern rehearsals. The draft was never adopted."]),
 ("long", "How many wooden tokens does a visitor need for the Tula observatory lift?", [
  "The Tula observatory lift requires two wooden tokens for each visitor. A separate paper ticket permits entry to the map room.",
  "The Tula observatory map room requires two wooden tokens. The lift ticket requirements are not included in this fictional notice.",
  "The Runi observatory lift requires three wooden tokens for each visitor. A steward collects the tokens beside the yellow lift door.",
  "Children painted two wooden tokens beside the Tula observatory lift as decoration. The painting does not state any admission requirement."]),
 ("long", "What should the Pavo puppet troupe do after the final curtain?", [
  "After the final curtain, the Pavo puppet troupe places its puppets in the padded cedar case. It checks every string before closing.",
  "Before the first curtain, the Pavo puppet troupe removes its puppets from the padded cedar case. The evening cleanup is not described.",
  "After the final curtain, the Dena puppet troupe hangs its puppets on a curved wall rack. A cloth screen hides the rack.",
  "The Pavo puppet troupe keeps scenery in a padded cedar case after the final curtain. This instruction does not cover the puppets."]),
 ("long", "Which path reaches the painted tide garden from Nolo square?", [
  "From Nolo square, the path beside the white windmill reaches the painted tide garden. A row of round stones marks the turn.",
  "From Nolo square, the path beside the black windmill reaches the painted tide garden. A row of square stones marks the turn.",
  "The path beside the white windmill reaches the quiet reed garden from Nolo square. It does not lead to the tide garden.",
  "An unfinished map connects Nolo square to the painted tide garden through a tunnel. A note warns that the tunnel was imaginary."]),
]
FILLER = ("This account belongs to an invented village archive. The surrounding pages describe paper decorations, "
          "empty display shelves, a painted ceiling, quiet corridors, and a visitor sketchbook. "
          "These background details provide texture for the fictional scene without changing the notice above. ")
TARGET = {"short": 48, "medium": 112, "long": 224}

def build():
    rows = []
    for i, (stratum, query, seeds) in enumerate(CASES, 1):
        passages = []
        for j, seed in enumerate(seeds, 1):
            words = seed.split()
            fill = (FILLER * 20).split()
            words += fill[:TARGET[stratum] - len(words)]
            passages.append({"id": f"q{i:02d}p{j}", "text": " ".join(words)})
        rows.append({"id": f"q{i:02d}", "stratum": stratum, "query": query, "passages": passages})
    return {"schema": 1, "purpose": "fictional engineering agreement only; no relevance labels", "queries": rows}

if __name__ == "__main__":
    Path(__file__).with_name("fixtures.json").write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")
