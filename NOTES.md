# Approach

## Architecture

I have a default go-to tech stack and architecture that works very well for many applications
like this (web-based SaaS that can scale and handle heavy async tasks). It is based on
'boring', well-established technology that is well-documented and with which AI coding agents
are very familiar: Django + DRF + React + Redis + Celery. All of those
frameworks/technologies/components have been around for a long time and are known to work
well. Unless a requirement specifically calls for a different approach, I generally start with
that setup. Benefits:

* A very capable, secure, feature-rich, and well-documented backend framework (Django).
* A well-established, powerful library to serve a REST API (DRF).
* A powerful, established framework for a dynamic frontend experience (React).
* A solid message queue and broker (Redis).
* A feature-rich, established framework for asynchronous task workers, with good Django
  compatibility (Celery).
* For a database, to keep it simple, we are currently using SQLite. We can change this to
  any other relational DB we like.
* For LLM requests, I use OpenRouter as a proxy, since it lets me easily try different
  models without changing any code.
* For web search, I chose Tavily, since it returns search results in an agent-friendly,
  uncluttered form.

# Getting started

## Environment variables

A `./env-example` file is provided, which shows all available configuration options. Make a
copy of that file to .env and then modify any settings. You can leave almost everything at its
default. However, you should at least set `DEFAULT_LLM_API_KEY`, and if you don’t use OpenAI
directly, then also `DEFAULT_LLM_URL`. You also need to provide `TAVILY_API_KEY` (Tavily gives
you some free credits to start with).

I like to make it as simple as possible for a new developer to get started. Therefore, I
always provide a single script (`./start_all.sh`) to bring up all required services. The
script chooses non-standard ports and runs Redis inside a Docker container to avoid disturbing
any existing server instances on the development machine.

# How I built it

## Total time to build

I worked on this in several stages over the course of three days. If you review the date/time
of the various commit messages, you see that I probably spent around 5 hours total. The core
features were done in around 2.5 hours. I then spent the remainder of the time adding
sentiment analysis, which was not part of the original product brief.

## Going beyond the initial product brief

For a few items, I chose to go beyond the minimum required by the PRD.

1. Knowing that we have a system capable of running many async tasks in parallel, I
   requested that the system support the parallel execution of many runs. So, multiple
   companies can be researched at the same time.
2. The product brief didn’t ask for it, but I always try to use the cheapest models I can
   get away with in production code. Therefore, I focused on making this work with a
   small, older model (gpt-4o-mini). A full research run now costs around $0.02 in
   OpenRouter. I did not spend time evaluating quality across different models.
3. Sentiment analysis. I added this later, after the initial implementation was done. I
   just thought this would be really interesting to see. But I think that requires more
   tuning to be actually helpful (didn’t have time to really dive into it).
4. Optional inclusion of additional sources, which may be questionable as per the brief.
   Such as Reddit (arguably a link-aggregator, but also a discussion forum).
5. The system allows for the configuration of different LLMs for different parts of the
   job (research, summary creation, sentiment assessment)

## The agent and our ‘conversation’

I generally used Claude Code, and specifically, Opus 4.8 on 'medium'. You can see a full dump
of my session with it in `docs/claude-session-1.txt` (which is about creating the detailed
implementation plan from the initial ideas), and `docs/claude-session-2.txt` (which is about
the implementation, plus subsequent iteration on a few extra features and bug fixes).

On a few occasions, I also asked OpenAI’s Codex for a plan and code review.

### The initial PRD (from idea outline to high-level spec)

I extended the initial product brief with more instructions.

1. I took the product brief I was given and created `plans/PRD-initial.md`. In that
   document, I provided an overview of the architecture I described above, as well as the
   features and styles I wanted to see implemented. Review this document to get a sense
   for what I wanted and how I phrased it.
2. Note that sentiment analysis was not part of the initial plan.
3. I then worked with Claude on expanding this and on arriving at a detailed high-level
   spec (`plans/INITIAL.md`). This went through several rounds of adverserial plan reviews
   by clean-context agents (I use my custom command `/review-plan` for this, which is quite
   effective). After that was complete, I also asked Codex for a plan review.
4. NOTE: This step took the most hands-on work, since I went through a few clarifying
   questions.

### Implementation

1. Once the initial high-level spec was settled, I asked Claude to create a detailed
   implementation plan (`plans/IMPLEMENTATION.md`).
2. This implementation plan also went through several rounds of review via the
   `/review-plan` command. In addition, Codex was used for additional review rounds.
3. Once the implementation plan was finalised, I used my custom `/implement` command to
   not only implement the whole system, but also run it through several rounds of code
   review.  I also used Codex again for yet another round of code reviews.
4. NOTE: While this step took the longest time, most of it was spent by the agent(s)
   working on their own, and I was off doing other things. My custom commands
   (`/review-plan` and `/implement`) carry a lot of weight and tend to make the
   implementation mostly a background job.
5. Once the agents finished implementing, I started the system. It worked on the first
   try! But I made several improvement requests (better error handling, some UI
   improvements, etc.). It took just a few rounds (two or three prompts) to get the base
   system to an acceptable state. Afterward, the remainder of my prompting was to add the
   ad-hoc sentiment feature.

# Unfinished business

## Data quality

* Reddit posts are unreliably dated via Tavily. To get reliable dates for them, we would
  have to issue separate HTTP requests to the posts to get the actual date.
* The sentiment’s graph time scale jumps around a bit if you filter out categories. It
  should stick to a fixed time duration for rendering purposes (not just based on the
  currently visible data points).
* Smarter prompting and search queries to better separate self-congratulatory press
  releases (there are still some that made it through).

## The sentiment chart

* Hovering over a dot in the sentiment graph may not necessarily pop up the info about
  that dot. The hover ‘selection’ is purely based on the x-axis position of the mouse
  pointer, and if there are many dots of different sentiment in roughly the same position,
  you may see the pop-up for the wrong dot.

## Additional nice-to-haves and next things to do

* Currently, the system doesn’t use web-sockets for dynamic UI updates, but instead polls
  the server every 2 seconds. This works well for now, and is only something we would have
  to change when users really scale up.
* It would be nice to show sentiment judgment for categories on the run-view page
  overview.
* Sentiment analysis looks interesting, and everyone likes to look at graphs. But I think
  it’s not 100% useful yet. This feature would require some more fine-tuning and work.
* Ability to re-run individual categories, not just the whole run.
* Just using Instructor for structured output validation from the LLM, rather than custom
  code.
* Better logging. It’s all still a bit scattered.
* Creation and export of reports.
* All the proper CiCd, deployment, etc.
* A strict test framework that can be the foundation of a solid harness.
* Proper login and observability, and account management.
* Ability to provide a prompt when starting a run, in order to customise the analysis.


