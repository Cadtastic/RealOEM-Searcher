# BMW Motorrad

Brand notes for skills and parsers. Registry data lives in `brand.toml`.

- Product `M`. Vehicle ids share the brand segment `BMW` with cars, e.g.
  `0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_`; the registry resolves them by series pattern
  (`K…` incl. KR1/KM3, `R<digit>…`, `T<digit>…` for old bikes such as T24) or by `product="M"`.
- No body (`ohne`) or engine cascade levels; vehicle specs show Body `N/A`.
- Diagram and subgroup names are printed twice ("Engine Engine"); `dedupe_repeated_names = true`.
- Supplements may be German (`SILBER`) even under `enUS`; fewer prices are shown.
- WMI prefixes: `WB1`, `WB3`.
