"""Every Indeed page selector lives here, so the bot can be recalibrated in one place if Indeed changes
its pages. Each entry is a list tried in order. Last checked against Indeed's public markup in 2026;
run `python -m jobbot doctor --live` on Anagha's PC to confirm they still match."""

SEARCH_CARD = ["div.job_seen_beacon", "li div.cardOutline", "[data-testid='slider_item']"]
CARD_LINK = ["a.jcs-JobTitle", "h2.jobTitle a", "a[data-jk]"]
CARD_TITLE = ["h2.jobTitle span[title]", "h2.jobTitle span", "a.jcs-JobTitle span"]
CARD_COMPANY = ["[data-testid='company-name']", "span.companyName", ".company_location [data-testid='company-name']"]
CARD_LOCATION = ["[data-testid='text-location']", "div.companyLocation"]
CARD_SALARY = ["[data-testid='attribute_snippet_testid']", ".salary-snippet-container", ".metadata.salary-snippet-container"]
CARD_EASY_APPLY = ["[data-testid='indeedApply']", ".iaLabel", "span:has-text('Easily apply')"]

JOB_TITLE = ["[data-testid='jobsearch-JobInfoHeader-title']", "h1.jobsearch-JobInfoHeader-title", "h1"]
JOB_COMPANY = ["[data-testid='inlineHeader-companyName']", "[data-company-name='true']", ".jobsearch-CompanyInfoContainer a"]
JOB_LOCATION = ["[data-testid='inlineHeader-companyLocation']", "[data-testid='job-location']", "#jobLocationText"]
JOB_SALARY = ["#salaryInfoAndJobType", "[data-testid='jobsearch-OtherJobDetailsContainer']"]
JOB_DESCRIPTION = ["#jobDescriptionText", "[data-testid='jobsearch-JobComponent-description']"]
INDEED_APPLY_BUTTON = ["#indeedApplyButton", "button[id*='indeedApplyButton']", "[data-testid='indeedApplyButton-test']",
                       "button:has-text('Apply now')"]
EXTERNAL_APPLY = ["#applyButtonLinkContainer a", "button[aria-label*='company site']", "a:has-text('Apply on company site')",
                  "button:has-text('Apply on company site')"]

# Signed-out / signed-in markers in the Indeed header
SIGNED_IN = ["[data-gnav-element-name='AccountMenu']", "#AccountMenu", "[data-testid='AccountMenu']", "a[href*='/account/view']"]
SIGN_IN_LINK = ["a[data-gnav-element-name='SignIn']", "a[href*='secure.indeed.com/account/login']", "a:has-text('Sign in')"]
LOGIN_URL_PARTS = ["secure.indeed.com/auth", "secure.indeed.com/account/login", "/account/login"]

# Human verification. The bot never solves or bypasses these: it stops and tells Anagha.
CAPTCHA = ["iframe[src*='hcaptcha']", "iframe[src*='recaptcha']", "iframe[src*='challenges.cloudflare.com']",
           "#challenge-form", "[data-testid='captcha']", "#px-captcha"]
CAPTCHA_TEXT = r"verify (?:you are|that you're) (?:a )?human|additional verification required|unusual (?:activity|traffic)|are you a robot|just a moment|security check|complete the captcha|one more step"

# Indeed Apply (smartapply) steps
APPLY_CONTINUE = ["button[data-testid*='continue-button']", "button:has-text('Continue')", "button:has-text('Next')"]
APPLY_SUBMIT = ["button[data-testid*='submit-application']", "button:has-text('Submit your application')",
                "button:has-text('Submit application')"]
APPLY_FILE_INPUT = ["input[type='file']"]
APPLY_UPLOAD_OPTION = ["[data-testid*='resume-selection-file-resume-upload']", "button:has-text('Upload a different file')",
                       "label:has-text('Upload a resume')", "button:has-text('Upload')"]
APPLY_QUESTION = ["[data-testid*='question']", ".ia-Questions-item", "fieldset", "div.ia-BasePage-component > div label"]
APPLY_CONFIRMATION_TEXT = r"application (?:has been |was )?submitted|you(?:'ve| have) applied|thanks for applying|your application has been sent"
APPLY_ERROR_TEXT = r"answer this question|this field is required|please (?:select|enter|fix)|is required"
