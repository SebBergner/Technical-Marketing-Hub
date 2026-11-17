# Hub search API

For a program that needs to search the Hub's demos and get links to them and to their
files, such as Growth OS (Seb, 2026-11-17). One endpoint, read-only.

```
GET /api/v1/search
```

It is the Hub's own search: the same search-term groups ("MBSE" also finds "Model-Based
Systems Engineering"), the same ranking, and the same rule for who may see what.

## 1. Get a token

A Hub administrator makes one: **Admin → Users & groups → API tokens → New token**.

- Give it a name (such as `Growth OS`), an owner, and these permissions:
  - `view_hub`: required. Without it every call is refused (403).
  - `preview` and `download`: needed for the file links. Without them the files are
    listed by name only.
  - `access_internal`: only if the program may see PTC Only demos' files.
- The secret is shown once, when it is made: `tmh_<id>_<secret>`. Store it like a
  password. A token expires (90 days unless chosen otherwise) and can be revoked.

Every request sends it as a header:

```
Authorization: Bearer tmh_<id>_<secret>
```

A token reaches `/api/` only, never the Hub's pages.

## 2. The request

| Parameter | Meaning |
|---|---|
| `q` | search text. Leave out to list by newest. |
| `product` | a product, such as `Creo Parametric`. Repeat to allow several. |
| `family` | a product family, such as `Creo`, `Windchill`. Repeatable. |
| `umbrella` | one of the eight families the Hub navigation browses by. Repeatable. |
| `segment` | `CAD`, `PLM`, `ALM`, ... Repeatable. |
| `industry` | Repeatable. |
| `type` | `video`, `vdk`, `ldk`, ... Repeatable. |
| `language` | `en`, `de`, ... Repeatable. |
| `limit` | results per call, 1 to 100 (default 20). |
| `offset` | how many to skip, for the next page (default 0). |

Different parameters narrow (segment AND type); repeats of one parameter widen (CAD OR PLM).

```bash
curl -H "Authorization: Bearer tmh_<id>_<secret>" \
  "https://<hub-address>/api/v1/search?q=lifecycle&segment=ALM&type=vdk&limit=2"
```

## 3. The response

```json
{
  "query": "lifecycle",
  "total": 43,
  "limit": 2,
  "offset": 0,
  "items": [
    {
      "id": "lamborghini-intelligent-product-lifecycle",
      "title": "Lamborghini - Intelligent Product Lifecycle",
      "summary": "The Lamborghini Intelligent Product Lifecycle (IPL) Demo follows ...",
      "type": "vdk",
      "products": [],
      "families": [],
      "segment": "ALM",
      "industry": null,
      "language": "en",
      "published": "2026-10-06",
      "customer_facing": false,
      "internal": true,
      "hub_url": "https://<hub-address>/#/asset/lamborghini-intelligent-product-lifecycle",
      "files_available": true,
      "files": [
        {
          "name": "Lamborghini_IPL_Demo-Script.docx",
          "kind": "document",
          "size_bytes": 260832,
          "preview_url": "https://<hub-address>/api/assets/lamborghini-intelligent-product-lifecycle/files/<file-id>/preview",
          "download_url": "https://<hub-address>/api/assets/lamborghini-intelligent-product-lifecycle/files/<file-id>/download"
        }
      ]
    }
  ]
}
```

(Real output from 2026-11-17, shortened: one demo, one file, the summary cut.)

- `total` is every match; `items` is this page. The next page is `offset` plus `limit`,
  until `offset` reaches `total`.
- `summary` is the demo's description, cut at 500 characters.
- `hub_url` is the demo's page. Open it in a browser; the person signs in as usual.
- `files` lists the demo's files. `preview_url` and `download_url` are Hub addresses;
  call them with the same Bearer header. A download answers with a redirect to a
  temporary SharePoint link (about an hour), so ask again rather than keeping it.
- `files_available` is `false` when none of the demo's files can be opened by this
  token. The reasons: the demo is PTC Only and the token lacks `access_internal`, the
  token lacks `preview` and `download`, or the demo has no files in the Hub (a Consensus
  recording). `files` then holds names without links, or nothing.
- `products` and `families` can be empty: not every demo has them filled in.
- New fields may be added to the response later. Existing ones are not renamed or removed
  without telling the programs that use them.

## 4. Errors

| Status | Meaning |
|---|---|
| 401 | no token, or an invalid, expired or revoked one |
| 403 | the token lacks `view_hub` |
| 422 | a parameter is wrong, such as `limit=500` |

## 5. What it does not do

- It does not count as a search in Content Health (those numbers are for people).
- It shows only what the token's permissions show a person: GXC demos only if the
  Hub's GXC rules allow, archived and unpublished demos never.
- It does not search inside files. Use the Hub's Advanced Search for that.
