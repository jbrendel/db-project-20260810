PRD provided by client
======================

The application
---------------
Build a basic web app that accepts:
    • A company name; and/or
    • A company homepage URL.

The app should start a background job that finds as much content about the company as possible
from the last 36 months.

Content types may include:
    • News articles
    • Trade publications
    • Blog posts
    • Press releases
    • Major social posts
    • Newsletters
    • Podcasts

Content should not include:
    • product review/comparison pages
    • ecommerce pages
    • The company’s own channels (ie their own website, blog, LinkedIn, etc)
    • Link aggregator sites

The app should present results in an easily reviewable list for the user.

Running the system / user experience
------------------------------------
This is not a fully hosted, public web app for now. Instead, all we need to do is being able
to run it locally:

    1. Clone the repo.
    2. Add any required API keys to an `.env` file.
    3. Run the app locally. See notes below on how to run it.
    4. Enter a company name or homepage.
    5. Start a background job.
    6. See job status.
    7. Review returned content in a list.

Not required for now
--------------------
Authentication, hosting, CiCd


Additional guidance
===================
Architectural and usage decisions I am making from the start.

Architecture
------------
The tech stack has been chosen:

    * Tech stack: Django + DRF + React + SQlite + Redis + Celery (use Django's support for
      Celery).
    * Frontend: Django should merely serve the API for the React frontend, we are not using
      Django's server side rendered pages. We use Vite as a React development server.
    * We use AI from within the product to conduct research and present results.
      For each "type" of AI call, we want to be able to configure separate LLMs. We
      use an OpenAI compatible API, so we can either use the OpenAI API directly, or
      services like OpenRouter.
    * For any search operations, we use Tavily. This can be called directly as needed,
      or the search capability can be provided as a tool call to the LLMs.
    * We use Redis + Celery to run async tasks in the background.

Architectural guardrails:
-------------------------
    * We use a boring, well-established technology stack upon which to build our
      new application. This gives you access to lots of knowledge and documentation. We avoid
      using 'bleeding edge' technology and/or frameworks.
    * We fail loudly! If any config is missing, or input does not match expectations,
      we never paper over it or quietly try to make it work. Instead, we immediately
      and loudly throw exceptions! This means, if env vars are missing, we fail to start.
      If any input comes over APIs, we must return a meaningful 400 error with explanation.
      For user input we are strict in our validation and if it is insufficient or malformed,
      we return clear error messsages to the user input form.
    * Avoid overly defensive coding, instead fail! For example, if some JSON is supposed
      to have a field of a certain name, don't use `data.get('name')`, and then somehow
      handle `None`. Instead, write `data[name]` and if we get a `KeyError`, fail loudly.
      Likewise for object attributes. Don't write `hasattr(obj, 'name')` if we fully expect
      that object to have the attribute. Instead, write `obj.name` and loudly fail if we
      get an `AttributeError`.

Running the app locally:
------------------------
    * The system can be run on a Posix/Linux system where the bash shell is available.
    * The user should create a Python virtual environment and run `pip` or `uv pip` to
      install the requirements. Therefore, `requirements.txt` needs to exist.
    * There should be a ./start_all.sh script, which starts all necessary server
      instances (Django, Redis, Celery workers, etc.) and tails log files from all services.
      The script should also ensure that all requirements are installed, and should
      error out if they are not.
    * Note that we are running many systems and projects on our local development
      system. Therefore, do not assume that standard port numbers are available!
      The ./start_all.sh script should make sure that we choose available ports.
      It should print the chosen port to the log.
    * External services, such as Redis, might best be started as a docker container.
    * CTL-C should be caught, and all services should be shut down.
    * The ./start_all.sh script should accept a --reset-db parameter, which wipes
      the DB back to its original, empty state.

Configuration:
--------------
    * We use a `.env` file to provide all necessary settings. There should also be
      a `.env-example` file, which lists all possible parameters and explains their
      meaning.
    * The system will use LLMs to conduct research and create result presentations.
      There will be different 'call-points' for LLMs, for example to do particular
      research, or write particular summaries or reports.
    * For each type of LLM call (call-point'), we want to be able to configure different LLMs.
      Therefore, we should have a `call_llm()` function, that we use for all interactions
      with an LLM. It should take a `name` parameter. The value of `name` is used to
      select the appropriate set of env vars for the configuration. The following
      env vars may be defined for each LLM call:
        - `<name>_LLM_URL`
        - `<name>_LLM_API_KEY`
        - `<name>_LLM_MODEL`
        - `<name>_LLM_TOKENS`
        - `<name>_LLM_TEMP`
      If any of those variables is not defined, then the system should fall back
      to `DEFAULT_LLM_...`. The .env file is required to have `DEFAULT_...` versions
      of all five variables.
    * The `call_llm()` function should produce detailed logging
      for each call, specifically, it should log the model, the start and end time of
      the call, the number of tokens used (if available) and the full prompt and response.
      This should go into a separate log file.
    * For web search, a `TAVILY_API_KEY` variable must be defined.

User experience:
----------------
    * Past 'run' results should be visible on the home page. The user should be able
      to click on any of them and see the full results (the 'run-view').
    * The styling of our system should be modern, enterprise (no gimmicks, but sleek
      and professional). It is important that a run-view is easy to read, and results don't
      appear cluttered.
    * A new 'run' can be started at any time from a 'New run' button at the top right on
      the home page. Clicking that button should open a pop-up, which takes the user
      input, and which closes once the input has been received. This then needs to kick
      off the async research task(s).
    * Starting a run should prompt the user to enter a company name or URL (a single
      field can hold either). In addition, there should be checkboxes for borderline
      categories that the system may search, which are in addition to the ones listed
      above. For example, social media posts on Reddit, etc.
    * Note that the system can have multiple active runs going on at the same time.
    * If a run is currently active, it should be shown on the home page by showing a small
      spinner next to its name (the 'name' is the user input, such as company name or URL).
    * If the user clicks on a run that's currently in progress, the run-view should show
      all the information in each category that it has fully received so far. All other
      categories that are still incomplete, a spinner should be shown. If there are any
      background jobs still running, a banner across the top should say that this job
      is still in progress.
    * The start and end time of a run should be recorded.
    * On the run-view, the start and (once finished) end time of the run, and the total
      duration should be shown
    * A run has a status:
        - Red: It failed completely, no information about the company could be retrieved.
        - Yellow: Partial results were obtained, but some information is incomplete.
        - Green: All requested information was retrieved.
        - Blue: The run is still in progress and has not completed, yet.
    * On the run-view page, you can click a "Refresh" button, which immediately wipes
      the entire run-data and restarts this particular run from scratch (show an "Are you
      sure?" type of dialog first).
