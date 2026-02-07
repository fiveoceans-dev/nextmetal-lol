# NextMetal: League of Legends Data API

Professional-grade Knowledge Base API for League of Legends champions and game data.

## 🔑 Authentication

All requests to the Data API require a valid API Key. You can generate and manage your keys in the **Developer Portal** section of your NextMetal dashboard.

### Methods
1.  **HTTP Header (Recommended)**:
    `API-KEY: NMSK-your_key_here`
2.  **Query Parameter**:
    `?api_key=NMSK-your_key_here`

---

## 🌍 Service Endpoints

| Environment | Base URL |
| :--- | :--- |
| **Local** | `http://api.localhost:8080/v1/data` |
| **Production** | `https://api.nextmetal.org/v1/data` |

### 1. List Champions
Retrieve a paginated list of all champions currently in the NextMetal database.

**Path**: `GET /lol/champions`

**Parameters**:
*   `page`: (Optional) Page number (default: 1)
*   `limit`: (Optional) Items per page (default: 20)
*   `query`: (Optional) Search champions by name.
*   `fields`: (Optional) Comma-separated list of fields to return.

**Example Request**:
```bash
curl -X GET "https://api.nextmetal.org/v1/data/lol/champions?limit=5&fields=name,slug" 
  -H "API-KEY: NMSK-YOUR_KEY"
```

---

### 2. Get Champion Detail
Retrieve full details for a specific champion. This endpoint features **Lazy Loading**: if the champion is not in the NextMetal database, it will be automatically fetched from Riot Games, cached, and returned.

**Path**: `GET /lol/champions/:slug`

**Example Request**:
```bash
curl -X GET "https://api.nextmetal.org/v1/data/lol/champions/jinx" 
  -H "API-KEY: NMSK-YOUR_KEY"
```

---

## 🎯 Advanced Features

### Field Selection (`?fields=`)
Optimize your network usage by requesting only the data points you need. You can pick top-level fields or fields nested inside the `metadata` JSON.

**Common Fields**:
*   `name`: The champion's name.
*   `description`: Short blurb or lore.
*   `imageUrl`: Link to the splash art.
*   `stats`: Full combat statistics (HP, AD, Armor).
*   `spells`: Abilities and passive details.

**Example: Request only Lore and Stats**
```bash
GET /lol/champions/aatrox?fields=name,lore,stats
```

### Data Persistence
NextMetal mirrors Riot's Data Dragon. While core fields (`name`, `slug`, `imageUrl`) are standardized, the `metadata` field contains the original high-fidelity JSON from the source, allowing you to access:
*   `info`: Difficulty, Attack, Defense rankings.
*   `tags`: Mage, Marksman, Support, etc.
*   `partype`: Resource type (Mana, Energy, etc.).

---

## 🛡️ Rate Limits
Standard API keys are limited to **60 requests per minute**. For higher throughput, please contact `support@nextmetal.org`.

## 🆘 Support
For documentation issues or feature requests, visit our GitHub repository or contact the NextMetal developer relations team.
