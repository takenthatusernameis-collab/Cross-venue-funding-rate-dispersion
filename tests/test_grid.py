import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cross_venue_funding_dispersion.grid import config_id,expand_grid,load_grid,validate_grid


class GridTests(unittest.TestCase):
    def setUp(self):
        self.config=load_grid(ROOT/"configs/cross_venue_funding_dispersion_grid_v1.json")

    def test_exactly_108_unique_configs(self):
        items=expand_grid(self.config)
        self.assertEqual(len(items),108)
        self.assertEqual(len({tuple(sorted(x.items())) for x in items}),108)
        self.assertEqual(validate_grid(self.config),[])

    def test_anchor_is_fvd053(self):
        items=expand_grid(self.config)
        self.assertEqual(config_id(items.index(self.config["enumeration"]["primary_anchor"])+1,self.config),"FVD053")

    def test_duplicate_axis_name_fails(self):
        bad=dict(self.config)
        bad["axes"]=[dict(x) for x in self.config["axes"]]
        bad["axes"][0]["name"]=bad["axes"][1]["name"]
        self.assertTrue(validate_grid(bad))


if __name__=="__main__":
    unittest.main()
