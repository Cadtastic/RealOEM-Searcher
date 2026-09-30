# BMW (cars)

Brand notes for skills and parsers. Registry data lives in `brand.toml`.

- Fallback brand for product `P` (cars): any series not claimed by MINI or Rolls-Royce is BMW,
  including BMW i, M/Motorsport (`MOSP`) and Zinoro.
- Vehicle ids use the brand segment `BMW`, e.g. `VB13-USA-10-2005-E90-BMW-325i`; Zinoro
  (BMW Brilliance, China) ids use `Zinoro`.
- Series codes are opaque; LCI (facelift) series end in `N` (`E90N`). Read codes from links, never
  from labels.
- Classic catalog (`archive=1`) holds E21, E30, E36, E46, E39, E38, E31, Z3 and others; Classic cars
  add Steering and Transmission cascade levels.
- WMI prefixes: `WBA`, `WBS` (M), `WBY` (i), `WBX`, US-built `5UX`, `5UM`, `5YM`, `4US`, Mexico `3MW`,
  China `LBV`.
