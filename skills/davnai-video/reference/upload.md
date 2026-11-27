# Uploading the final to Davnai

1. Ask first: "Upload this to Davnai?" Only the final the person chose.
2. `python davnai.py probe "<final>"` prints the file name, size, length, width and height.
3. Call Davnai's `upload_from_computer` with those numbers (and `project_id` if the person named a project). It checks their plan and returns a `ticket`.
4. `python davnai.py upload "<final>" "<ticket>"` sends the file in parts straight to Davnai (it never passes through the chat) and prints the video id. The ticket lasts 6 hours; if it expires, call `upload_from_computer` again.
5. Then post with `create_posts` (your own words, in their Brand Kit voice) and the video id. Posts wait for approval in Davnai unless the person has said otherwise.

If the computer can't run the script, give the person Davnai's upload link (upload_link) instead.
