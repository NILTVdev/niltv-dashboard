"""Pure tests for the Google Form row mapping (no DB, no network)."""

from backend.onboarding import form_rows

GEN1 = ["Timestamp", "Email Address", "Name", "Email", "Phone Number", "University", "Sport",
        "Year this Fall", "Link to your best content!", "IG link", "Number of Instagram Followers",
        "TikTok link", "Number of TikTok Followers", "Youtube link", "Number of YouTube Subscribers",
        "Linkedin link", "Facebook link", "Number of Followers on other platforms (please specify)",
        "What type of content are you producing?", "What are your goals in the content creation space?"]

GEN3 = ["Timestamp", "personal email", "First Name", "Last Name", "School", "School Email", "Phone #",
        "Sport", "Year (F26)", "link to best content", "Insta", "insta followers", "tiktok", "TT followers",
        "YT link", "Yt follow", "Accounts & Number of Followers on other platforms (please explain)",
        "content category", "Goals?", "NIL Deals?", "what companies would you want to partner with?"]


def test_gen1_mapping():
    row = ["1/2/2026 12:00:00", "applicant352@example.com", "Sample Applicant", "Applicant462@Example.edu", "5550100200",
           "Example State University ", "Football", "Sophomore", "https://instagram.com/reel/x",
           "https://www.instagram.com/sample_applicant/", "1,234", "https://tiktok.com/@sample_applicant", "743", "", "5",
           "", "", "", "Highlights", "Grow"]
    p = form_rows.row_to_payload(GEN1, row, tab="Form Responses 1")
    assert p["email"] == "applicant352@example.com"
    assert p["collegeEmail"] == "applicant462@example.edu"
    assert p["firstName"] == "Sample" and p["lastName"] == "Applicant"
    assert p["university"] == "Example State University" and p["sport"] == "Football" and p["year"] == "Sophomore"
    assert p["instagram"] == "https://www.instagram.com/sample_applicant/" and p["instagramFollowers"] == "1,234"
    assert p["tiktokFollowers"] == "743" and p["youtubeSubscribers"] == "5"
    assert p["contentType"] == "Highlights" and p["purpose"] == "Grow"
    assert p["source"] == "google-form" and p["consentVersion"] == "google-form-legacy"
    assert form_rows.parse_timestamp(p["submittedAt"]).year == 2026


def test_gen3_mapping_with_first_last_and_nil_deals():
    row = ["1/3/2026 12:00:00", "applicant997@example.com", "Taylor ", "Example ", "Sample University",
           "Applicant908@Example.edu", "5550100200", "Men's Track and Field", "Junior", "https://ig/p/x",
           "taylor_example", "2100", "@taylor", "900", "", "", "", "Training", "Brand", "Yes", "Nike"]
    p = form_rows.row_to_payload(GEN3, row)
    assert p["email"] == "applicant997@example.com"
    assert p["collegeEmail"] == "applicant908@example.edu"
    assert p["firstName"] == "Taylor" and p["lastName"] == "Example"   # cells are trimmed
    assert p["university"] == "Sample University" and p["phone"] == "5550100200"
    assert p["instagram"] == "taylor_example" and p["instagramFollowers"] == "2100"
    assert p["tiktok"] == "@taylor" and p["tiktokFollowers"] == "900"
    assert p["nilDealsDone"] == "Yes" and p["nilDealsWanted"] == "Nike"


def test_email_fallbacks():
    hdr = ["Timestamp", "Email Address", "Name", "Email"]
    # gen2: account email blank, "Email" is personal
    p = form_rows.row_to_payload(hdr, ["1/4/2026 12:00:00", "", "Alex Example", "applicant349@example.com"])
    assert p["email"] == "applicant349@example.com" and "collegeEmail" not in p
    # only an .edu in the generic column -> both email and college
    p = form_rows.row_to_payload(hdr, ["1/4/2026 12:00:00", "", "A B", "applicant507@example.edu"])
    assert p["email"] == "applicant507@example.edu" and p["collegeEmail"] == "applicant507@example.edu"
    # no email at all -> skipped
    assert form_rows.row_to_payload(hdr, ["1/4/2026 12:00:00", "", "Nobody", ""]) is None


def test_is_form_tab_rejects_roster_and_contact_tabs():
    assert form_rows.is_form_tab(GEN1)
    assert not form_rows.is_form_tab(["NAME", "SCHOOL", "SPORT", "YEAR (F26)", "Insta Followers"])
    assert not form_rows.is_form_tab(["NAME", "EMAIL", "PHONE #"])   # no timestamp


def test_unknown_columns_are_kept_as_extra():
    hdr = ["Timestamp", "Email", "Favorite snack"]
    p = form_rows.row_to_payload(hdr, ["1/1/2026 10:00:00", "applicant961@example.com", "pretzels"])
    assert p["extra"] == {"Favorite snack": "pretzels"}


def test_split_name():
    assert form_rows.split_name("Pat J Example") == ("Pat", "J Example")
    assert form_rows.split_name("Cher") == ("Cher", "")
    assert form_rows.split_name("") == ("", "")


def test_blank_timestamp_header_detected_by_values():
    hdr = ["", "personal email", "First Name", "Last Name", "School"]
    rows = [["1/5/2026 12:00:00", "applicant724@example.com", "A", "B", "Sample University"], ["1/6/2026 9:00:00", "applicant323@example.com", "C", "D", "Sample University"]]
    assert not form_rows.is_form_tab(hdr)             # header alone: no timestamp
    assert form_rows.is_form_tab(hdr, rows)           # values reveal it
    cmap = form_rows.map_header(hdr, rows)
    p = form_rows.row_to_payload(hdr, rows[0], cmap=cmap)
    assert p["submittedAt"] == "1/5/2026 12:00:00" and p["firstName"] == "A" and p["university"] == "Sample University"


def test_site_form_2026_columns():
    hdr = ["Timestamp", "Email Address", "First Name", "Last Name",
           "Does your college also have a channel? If so, which one?", "University", "College Email", "Phone Number",
           "Are you an international student?", "Sport", "Year this Fall", "Link to your official roster profile",
           "Instagram link", "# of Instagram Followers", "TikTok link", "# of TikTok Followers", "Youtube link",
           "# of YouTube Subscribers", "# of Followers on other platforms (please specify)",
           "What type of content are you producing? (nutrition, training, fashion, singing, etc.)",
           "What's your purpose behind posting?", "What companies have you done NIL deals with?",
           "What companies do you still want to partner with and why?"]
    row = ["1/7/2026 12:00:00", "applicant406@example.com", "Avery", "Sample", "Sample TV (Sample athletes)", "Sample University",
           "applicant202@example.edu", "5550100200", "No", "Women's Soccer", "Graduate Student",
           "https://example.edu/roster/avery-sample", "https://www.instagram.com/avery_sample/", "1200", "tiktok.com/@avery_sample",
           "800", "N/a", "N/a", "", "Training, lifestyle", "Share my sport", "None", "Local brands"]
    p = form_rows.row_to_payload(hdr, row)
    assert p["email"] == "applicant406@example.com" and p["collegeEmail"] == "applicant202@example.edu"
    assert p["campusChannel"] == "Sample TV (Sample athletes)"
    assert p["international"] == "No" and p["rosterLink"] == "https://example.edu/roster/avery-sample"
    assert p["university"] == "Sample University" and p["sport"] == "Women's Soccer" and p["year"] == "Graduate Student"
    assert p["instagramFollowers"] == "1200" and p["tiktokFollowers"] == "800"
    assert p["contentType"] == "Training, lifestyle" and p["purpose"] == "Share my sport"
    assert p["nilDealsDone"] == "None" and p["nilDealsWanted"] == "Local brands"


# -- Spelling guard + channel slugs -------------------------------------------

def test_school_canonical_and_channel_slug():
    from backend.onboarding import schools
    assert schools.canonical("Duke") == ("Duke University", True)
    assert schools.canonical("UNC chapel hill")[0] == "University of North Carolina at Chapel Hill"
    assert schools.canonical("Baylor University ") == ("Baylor University", True)
    assert schools.canonical("Texas University A&M")[0] == "Texas A&M University-College Station"
    assert schools.canonical("Cornerstone University") == ("Cornerstone University", True)
    assert schools.canonical("Baton rouge college") == ("Baton rouge college", False)   # unknown stays as typed
    assert schools.canonical("") == ("", False)
    assert schools.channel_slug("Salt City TV (Syracuse athletes)") == "saltcitytv"
    assert schools.channel_slug("truebluetv") == "truebluetv"
    assert schools.channel_slug("Not listed, but I would love to help launch one!") == "other"
    assert schools.channel_slug("", "Baylor University") == "brazostv"
    assert schools.channel_slug("", "Ohio State University") == ""


def test_cognito_pools_parsing(monkeypatch):
    from backend.config import get_settings
    from backend.onboarding import cognito
    monkeypatch.setattr(get_settings(), "cognito_user_pools", "")
    assert cognito.required() is False and cognito.pools() == []
    monkeypatch.setattr(get_settings(), "cognito_user_pools", "us-east-1_abc:client1, us-east-1_def:client2")
    assert cognito.pools() == [("us-east-1_abc", "client1"), ("us-east-1_def", "client2")]
    assert cognito.required() is True
    import pytest
    with pytest.raises(cognito.TokenError):
        cognito.verify("")
    with pytest.raises(cognito.TokenError):
        cognito.verify("not.a.jwt")
