from normalizers.booleans import normalize_boolean, normalize_mri_status


class TestNormalizeBoolean:
    def test_yes(self):
        assert normalize_boolean("yes") is True

    def test_no(self):
        assert normalize_boolean("no") is False

    def test_true_string(self):
        assert normalize_boolean("true") is True

    def test_false_string(self):
        assert normalize_boolean("false") is False

    def test_one(self):
        assert normalize_boolean("1") is True

    def test_zero(self):
        assert normalize_boolean("0") is False

    def test_y(self):
        assert normalize_boolean("Y") is True

    def test_n(self):
        assert normalize_boolean("N") is False

    def test_on(self):
        assert normalize_boolean("on") is True

    def test_off(self):
        assert normalize_boolean("off") is False

    def test_none_input(self):
        assert normalize_boolean(None) is None

    def test_empty_string(self):
        assert normalize_boolean("") is None

    def test_unrecognized(self):
        assert normalize_boolean("maybe") is None

    def test_whitespace_padding(self):
        assert normalize_boolean("  yes  ") is True

    def test_case_insensitive(self):
        assert normalize_boolean("YES") is True
        assert normalize_boolean("True") is True


class TestNormalizeMriStatus:
    def test_mr_safe(self):
        assert normalize_mri_status("MR Safe") == "MR Safe"

    def test_mr_conditional(self):
        assert normalize_mri_status("MR Conditional") == "MR Conditional"

    def test_mr_unsafe(self):
        assert normalize_mri_status("MR Unsafe") == "MR Unsafe"

    def test_case_insensitive(self):
        assert normalize_mri_status("mr safe") == "MR Safe"
        assert normalize_mri_status("MRI CONDITIONAL") == "MR Conditional"

    def test_mri_prefix(self):
        assert normalize_mri_status("MRI Safe") == "MR Safe"
        assert normalize_mri_status("MRI Conditional") == "MR Conditional"

    def test_none_input(self):
        assert normalize_mri_status(None) is None

    def test_empty_string(self):
        assert normalize_mri_status("") is None

    def test_unrecognized(self):
        assert normalize_mri_status("unknown status") is None

    def test_no_info(self):
        result = normalize_mri_status("no MRI safety info available")
        assert result == "Labeling does not contain MRI Safety Information"
