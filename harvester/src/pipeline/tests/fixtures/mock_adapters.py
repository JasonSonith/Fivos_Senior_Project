MEDTRONIC_INPACT_ADAPTER = {
    "extraction": {
        "device_name": ".product-heading h1",
        "model_number": ".table-wrapper .cfnDetailLink a",
        "specs_container": ".table-wrapper table",
    }
}

ABBOTT_ADAPTER = {
    "extraction": {
        "device_name": "h1.m-hbanner__content--title",
        "model_number": "section.cmp-text table tbody tr td:not([scope]):not([colspan]):first-child",
        "specs_container": "section.cmp-text table",
    }
}

BOSTON_SCIENTIFIC_ADAPTER = {
    "extraction": {
        "device_name": "h1",
        "model_number": "",
        "specs_container": "table",
    }
}

SHOCKWAVE_ADAPTER = {
    "extraction": {
        "device_name": "h1.main-heading",
        "model_number": "div.table-container table tbody tr td:not([scope]):first-child",
        "specs_container": "div.table-container table",
    }
}

COOK_ADAPTER = {
    "extraction": {
        "device_name": "h1.page-title span",
        "model_number": "table.specifications-table tbody tr td[data-swiftype-name=\"gpn-string\"]",
        "specs_container": "div.box.specifications table.specifications-table",
    }
}

GORE_ADAPTER = {
    "extraction": {
        "device_name": "h1.heading.heading--2",
        "model_number": "table.wf-dark tbody tr td:first-child",
        "specs_container": "div.table__container table.wf-dark",
    }
}

CORDIS_ADAPTER = {
    "extraction": {
        "device_name": "h1.h2.text-white",
        "model_number": "tbody.list td.sort-sku",
        "specs_container": "table",
    }
}

TERUMO_ADAPTER = {
    "extraction": {
        "device_name": "h1.cmp-heading__bar-terumo-light-green",
        "model_number": "div.cmp-richtext table tbody tr + tr td:first-child",
        "specs_container": "div.cmp-richtext table",
    }
}
