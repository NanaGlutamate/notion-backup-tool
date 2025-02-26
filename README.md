# NotionBackup

Back up your Notion content using the Notion API.

## What this repository does

* Incremental Backups via Notion API: no more need to update your app-token every 1, 2, or 3 months, more convenient and sustainable.

## What this repository does not do

* Rendering: It does not render your data into HTML or Markdown + CSV formats. Such rendering is often meaningless unless Notion completely stops its service.

## How to use

1. **COPY** the Repository: copy this repository, reupload it as your own account (or you cannot change it into private repository). 
2. Set up Notion App: Apply for your own Notion app and share the page you want to back up with this app.
3. Configure: Set your app token and the ID of the page you want to backup in `config.json`.
4. Upload to Github: upload into your private repository and **cancel comment in backup.yml**

```json
{
    "NOTION_TOKEN": "ntn_XXXXXXXX",
    "PG_ID": [
        "00000000"
    ]
}
```
