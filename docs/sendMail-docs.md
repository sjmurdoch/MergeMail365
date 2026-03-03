---
layout: Conceptual
monikers:
- graph-rest-1.0
defaultMoniker: graph-rest-1.0
versioningType: Ranged
title: 'user: sendMail - Microsoft Graph v1.0 | Microsoft Learn'
canonicalUrl: https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0
config_moniker_range: '>= graph-rest-1.0'
feedback_system: Standard
feedback_product_url: https://developer.microsoft.com/graph/support
author: SuryaLashmiS
ms.author: MSGraphDocsVteam
ms.suite: microsoft-graph
ms.subservice: outlook
uhfHeaderId: MSDocsHeader-MSGraph
toc_preview: true
recommendations: false
breadcrumb_path: /graph/ref-breadcrumb/toc.json
ms.service: microsoft-graph
ms.topic: reference
description: Send the message specified in the request body using either JSON or MIME format.
ms.localizationpriority: high
doc_type: apiPageType
ms.date: 2024-06-21T00:00:00.0000000Z
locale: en-us
document_id: d3b984b6-9100-69aa-f0f8-84bcdcea20dd
document_version_independent_id: 3f8b622d-becd-f287-98ac-18e408200523
updated_at: 2025-07-23T10:06:00.0000000Z
original_content_git_url: https://github.com/microsoftgraph/microsoft-graph-docs/blob/live/api-reference/v1.0/api/user-sendmail.md
gitcommit: https://github.com/microsoftgraph/microsoft-graph-docs/blob/82d0912dd8dd5a5f9a5e51d471f9c7f248f8e118/api-reference/v1.0/api/user-sendmail.md
git_commit_id: 82d0912dd8dd5a5f9a5e51d471f9c7f248f8e118
default_moniker: graph-rest-1.0
site_name: Docs
depot_name: MSDN.microsoft-graph-ref
page_type: conceptual
toc_rel: toc.json
feedback_help_link_type: ''
feedback_help_link_url: ''
word_count: 2951
asset_id: api/user-sendmail
moniker_range_name: 107bf06837724705de50667b407c0197
monikers:
- graph-rest-1.0
item_type: Content
source_path: api-reference/v1.0/api/user-sendmail.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/5fc61396-d075-4560-aece-fdbda73d243f
- https://authoring-docs-microsoft.poolparty.biz/devrel/cf9b82c5-b6dc-45f3-b005-b1bc5fc03bea
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/ad9437c1-8cda-4537-ad69-b4b263652e13
- https://authoring-docs-microsoft.poolparty.biz/devrel/0c85d34e-bfd2-4466-957c-f0b61e9692df
platformId: f24749d9-3294-7824-e388-c5be6e1c77b0
---

# user: sendMail - Microsoft Graph v1.0 | Microsoft Learn

Namespace: microsoft.graph

Send the message specified in the request body using either JSON or MIME format.

When using JSON format, you can include a [file attachment](resources/fileattachment) in the same **sendMail** action call.

When using MIME format:

- Provide the applicable [Internet message headers](https://tools.ietf.org/html/rfc2076) and the [MIME content](https://tools.ietf.org/html/rfc2045), all encoded in **base64** format in the request body.
- Add any attachments and S/MIME properties to the MIME content.

This method saves the message in the **Sent Items** folder.

Alternatively, [create a draft message](user-post-messages) to send later.

To learn more about the steps involved in the backend before a mail is delivered to recipients, see [here](/en-us/graph/outlook-things-to-know-about-send-mail).

This API is available in the following [national cloud deployments](/en-us/graph/deployments).

| Global service | US Government L4 | US Government L5 (DOD) | China operated by 21Vianet |
| --- | --- | --- | --- |
| ✅ | ✅ | ✅ | ✅ |

## Permissions

Choose the permission or permissions marked as least privileged for this API. Use a higher privileged permission or permissions [only if your app requires it](/en-us/graph/permissions-overview#best-practices-for-using-microsoft-graph-permissions). For details about delegated and application permissions, see [Permission types](/en-us/graph/permissions-overview#permission-types). To learn more about these permissions, see the [permissions reference](/en-us/graph/permissions-reference).

| Permission type | Least privileged permissions | Higher privileged permissions |
| --- | --- | --- |
| Delegated (work or school account) | Mail.Send | Not available. |
| Delegated (personal Microsoft account) | Mail.Send | Not available. |
| Application | Mail.Send | Not available. |

## HTTP request

```http
POST /me/sendMail
POST /users/{id | userPrincipalName}/sendMail
```

## Request headers

| Name | Type | Description |
| --- | --- | --- |
| Authorization | string | Bearer {token}. Required. Learn more about [authentication and authorization](/en-us/graph/auth/auth-concepts). |
| Content-Type | string | Nature of the data in the body of an entity. Required.  Use `application/json` for a JSON object and `text/plain` for MIME content. |

## Request body

When using JSON format, provide a JSON object with the following parameters.

| Parameter | Type | Description |
| --- | --- | --- |
| message | [Message](resources/message) | The message to send. Required. |
| saveToSentItems | Boolean | Indicates whether to save the message in Sent Items. Specify it only if the parameter is false; default is true. Optional. |

When specifying the body in MIME format, provide the MIME content as **a base64-encoded string** in the request body.

## Response

If successful, this method returns `202 Accepted` response code. It doesn't return anything in the response body.

> 
> **Note**: A `202 Accepted` response code indicates that the request has been accepted; however, it does not indicate that the request processing has completed. Delivery of the message is subject to [Exchange Online limitations and throttling](/en-us/office365/servicedescriptions/exchange-online-service-description/exchange-online-limits).

If the request body includes malformed MIME content, this method returns `400 Bad request` and the following error message: "Invalid base64 string for MIME content."

## Examples

### Example 1: Send a new email using JSON format

##### Request

**HTTP**

```http
POST https://graph.microsoft.com/v1.0/me/sendMail
Content-type: application/json

{
  "message": {
    "subject": "Meet for lunch?",
    "body": {
      "contentType": "Text",
      "content": "The new cafeteria is open."
    },
    "toRecipients": [
      {
        "emailAddress": {
          "address": "frannis@contoso.com"
        }
      }
    ],
    "ccRecipients": [
      {
        "emailAddress": {
          "address": "danas@contoso.com"
        }
      }
    ]
  },
  "saveToSentItems": "false"
}
```

**C#**

```csharp

// Code snippets are only available for the latest version. Current version is 5.x

// Dependencies
using Microsoft.Graph.Me.SendMail;
using Microsoft.Graph.Models;

var requestBody = new SendMailPostRequestBody
{Message = new Message{	Subject = "Meet for lunch?",	Body = new ItemBody	{		ContentType = BodyType.Text,		Content = "The new cafeteria is open.",	},	ToRecipients = new List<Recipient>	{		new Recipient		{			EmailAddress = new EmailAddress			{				Address = "frannis@contoso.com",			},		},	},	CcRecipients = new List<Recipient>	{		new Recipient		{			EmailAddress = new EmailAddress			{				Address = "danas@contoso.com",			},		},	},},SaveToSentItems = false,
};

// To initialize your graphClient, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=csharp
await graphClient.Me.SendMail.PostAsync(requestBody);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Go**

```go

// Code snippets are only available for the latest major version. Current major version is $v1.*

// Dependencies
import (  "context"  msgraphsdk "github.com/microsoftgraph/msgraph-sdk-go"  graphusers "github.com/microsoftgraph/msgraph-sdk-go/users"  graphmodels "github.com/microsoftgraph/msgraph-sdk-go/models"  //other-imports
)

requestBody := graphusers.NewItemSendMailPostRequestBody()
message := graphmodels.NewMessage()
subject := "Meet for lunch?"
message.SetSubject(&subject) 
body := graphmodels.NewItemBody()
contentType := graphmodels.TEXT_BODYTYPE 
body.SetContentType(&contentType) 
content := "The new cafeteria is open."
body.SetContent(&content) 
message.SetBody(body)

recipient := graphmodels.NewRecipient()
emailAddress := graphmodels.NewEmailAddress()
address := "frannis@contoso.com"
emailAddress.SetAddress(&address) 
recipient.SetEmailAddress(emailAddress)

toRecipients := []graphmodels.Recipientable {recipient,
}
message.SetToRecipients(toRecipients)

recipient := graphmodels.NewRecipient()
emailAddress := graphmodels.NewEmailAddress()
address := "danas@contoso.com"
emailAddress.SetAddress(&address) 
recipient.SetEmailAddress(emailAddress)

ccRecipients := []graphmodels.Recipientable {recipient,
}
message.SetCcRecipients(ccRecipients)
requestBody.SetMessage(message)
saveToSentItems := false
requestBody.SetSaveToSentItems(&saveToSentItems) 

// To initialize your graphClient, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=go
graphClient.Me().SendMail().Post(context.Background(), requestBody, nil)

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Java**

```java

// Code snippets are only available for the latest version. Current version is 6.x

GraphServiceClient graphClient = new GraphServiceClient(requestAdapter);

com.microsoft.graph.users.item.sendmail.SendMailPostRequestBody sendMailPostRequestBody = new com.microsoft.graph.users.item.sendmail.SendMailPostRequestBody();
Message message = new Message();
message.setSubject("Meet for lunch?");
ItemBody body = new ItemBody();
body.setContentType(BodyType.Text);
body.setContent("The new cafeteria is open.");
message.setBody(body);
LinkedList<Recipient> toRecipients = new LinkedList<Recipient>();
Recipient recipient = new Recipient();
EmailAddress emailAddress = new EmailAddress();
emailAddress.setAddress("frannis@contoso.com");
recipient.setEmailAddress(emailAddress);
toRecipients.add(recipient);
message.setToRecipients(toRecipients);
LinkedList<Recipient> ccRecipients = new LinkedList<Recipient>();
Recipient recipient1 = new Recipient();
EmailAddress emailAddress1 = new EmailAddress();
emailAddress1.setAddress("danas@contoso.com");
recipient1.setEmailAddress(emailAddress1);
ccRecipients.add(recipient1);
message.setCcRecipients(ccRecipients);
sendMailPostRequestBody.setMessage(message);
sendMailPostRequestBody.setSaveToSentItems(false);
graphClient.me().sendMail().post(sendMailPostRequestBody);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**JavaScript**

```javascript

const options = {authProvider,
};

const client = Client.init(options);

const sendMail = {
  message: {
    subject: 'Meet for lunch?',
    body: {
      contentType: 'Text',
      content: 'The new cafeteria is open.'
    },
    toRecipients: [
      {
        emailAddress: {
          address: 'frannis@contoso.com'
        }
      }
    ],
    ccRecipients: [
      {
        emailAddress: {
          address: 'danas@contoso.com'
        }
      }
    ]
  },
  saveToSentItems: 'false'
};

await client.api('/me/sendMail').post(sendMail);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**PHP**

```php

<?php
use Microsoft\Graph\GraphServiceClient;
use Microsoft\Graph\Generated\Users\Item\SendMail\SendMailPostRequestBody;
use Microsoft\Graph\Generated\Models\Message;
use Microsoft\Graph\Generated\Models\ItemBody;
use Microsoft\Graph\Generated\Models\BodyType;
use Microsoft\Graph\Generated\Models\Recipient;
use Microsoft\Graph\Generated\Models\EmailAddress;

$graphServiceClient = new GraphServiceClient($tokenRequestContext, $scopes);

$requestBody = new SendMailPostRequestBody();
$message = new Message();
$message->setSubject('Meet for lunch?');
$messageBody = new ItemBody();
$messageBody->setContentType(new BodyType('text'));
$messageBody->setContent('The new cafeteria is open.');
$message->setBody($messageBody);
$toRecipientsRecipient1 = new Recipient();
$toRecipientsRecipient1EmailAddress = new EmailAddress();
$toRecipientsRecipient1EmailAddress->setAddress('frannis@contoso.com');
$toRecipientsRecipient1->setEmailAddress($toRecipientsRecipient1EmailAddress);
$toRecipientsArray []= $toRecipientsRecipient1;
$message->setToRecipients($toRecipientsArray);

$ccRecipientsRecipient1 = new Recipient();
$ccRecipientsRecipient1EmailAddress = new EmailAddress();
$ccRecipientsRecipient1EmailAddress->setAddress('danas@contoso.com');
$ccRecipientsRecipient1->setEmailAddress($ccRecipientsRecipient1EmailAddress);
$ccRecipientsArray []= $ccRecipientsRecipient1;
$message->setCcRecipients($ccRecipientsArray);

$requestBody->setMessage($message);
$requestBody->setSaveToSentItems(false);

$graphServiceClient->me()->sendMail()->post($requestBody)->wait();

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**PowerShell**

```powershell

Import-Module Microsoft.Graph.Users.Actions

$params = @{message = @{	subject = "Meet for lunch?"	body = @{		contentType = "Text"		content = "The new cafeteria is open."	}	toRecipients = @(		@{			emailAddress = @{				address = "frannis@contoso.com"			}		}	)	ccRecipients = @(		@{			emailAddress = @{				address = "danas@contoso.com"			}		}	)}saveToSentItems = "false"
}

# A UPN can also be used as -UserId.
Send-MgUserMail -UserId $userId -BodyParameter $params

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Python**

```python

# Code snippets are only available for the latest version. Current version is 1.x
from msgraph import GraphServiceClient
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody
from msgraph.generated.models.message import Message
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
# To initialize your graph_client, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=python
request_body = SendMailPostRequestBody(message = Message(	subject = "Meet for lunch?",	body = ItemBody(		content_type = BodyType.Text,		content = "The new cafeteria is open.",	),	to_recipients = [		Recipient(			email_address = EmailAddress(				address = "frannis@contoso.com",			),		),	],	cc_recipients = [		Recipient(			email_address = EmailAddress(				address = "danas@contoso.com",			),		),	],),save_to_sent_items = False,
)

await graph_client.me.send_mail.post(request_body)

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

#### Response

```http
HTTP/1.1 202 Accepted
```

### Example 2: Create a message with custom Internet message headers and send the message

#### Request

**HTTP**

```http
POST https://graph.microsoft.com/v1.0/me/sendMail
Content-type: application/json

{
  "message": {
    "subject": "9/9/2018: concert",
    "body": {
      "contentType": "HTML",
      "content": "The group represents Nevada."
    },
    "toRecipients": [
      {
        "emailAddress": {
          "address": "AlexW@contoso.com"
        }
      }
    ],
    "internetMessageHeaders": [
      {
        "name": "x-custom-header-group-name",
        "value": "Nevada"
      },
      {
        "name": "x-custom-header-group-id",
        "value": "NV001"
      }
    ]
  }
}
```

**C#**

```csharp

// Code snippets are only available for the latest version. Current version is 5.x

// Dependencies
using Microsoft.Graph.Me.SendMail;
using Microsoft.Graph.Models;

var requestBody = new SendMailPostRequestBody
{Message = new Message{	Subject = "9/9/2018: concert",	Body = new ItemBody	{		ContentType = BodyType.Html,		Content = "The group represents Nevada.",	},	ToRecipients = new List<Recipient>	{		new Recipient		{			EmailAddress = new EmailAddress			{				Address = "AlexW@contoso.com",			},		},	},	InternetMessageHeaders = new List<InternetMessageHeader>	{		new InternetMessageHeader		{			Name = "x-custom-header-group-name",			Value = "Nevada",		},		new InternetMessageHeader		{			Name = "x-custom-header-group-id",			Value = "NV001",		},	},},
};

// To initialize your graphClient, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=csharp
await graphClient.Me.SendMail.PostAsync(requestBody);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Go**

```go

// Code snippets are only available for the latest major version. Current major version is $v1.*

// Dependencies
import (  "context"  msgraphsdk "github.com/microsoftgraph/msgraph-sdk-go"  graphusers "github.com/microsoftgraph/msgraph-sdk-go/users"  graphmodels "github.com/microsoftgraph/msgraph-sdk-go/models"  //other-imports
)

requestBody := graphusers.NewItemSendMailPostRequestBody()
message := graphmodels.NewMessage()
subject := "9/9/2018: concert"
message.SetSubject(&subject) 
body := graphmodels.NewItemBody()
contentType := graphmodels.HTML_BODYTYPE 
body.SetContentType(&contentType) 
content := "The group represents Nevada."
body.SetContent(&content) 
message.SetBody(body)

recipient := graphmodels.NewRecipient()
emailAddress := graphmodels.NewEmailAddress()
address := "AlexW@contoso.com"
emailAddress.SetAddress(&address) 
recipient.SetEmailAddress(emailAddress)

toRecipients := []graphmodels.Recipientable {recipient,
}
message.SetToRecipients(toRecipients)

internetMessageHeader := graphmodels.NewInternetMessageHeader()
name := "x-custom-header-group-name"
internetMessageHeader.SetName(&name) 
value := "Nevada"
internetMessageHeader.SetValue(&value) 
internetMessageHeader1 := graphmodels.NewInternetMessageHeader()
name := "x-custom-header-group-id"
internetMessageHeader1.SetName(&name) 
value := "NV001"
internetMessageHeader1.SetValue(&value) 

internetMessageHeaders := []graphmodels.InternetMessageHeaderable {internetMessageHeader,internetMessageHeader1,
}
message.SetInternetMessageHeaders(internetMessageHeaders)
requestBody.SetMessage(message)

// To initialize your graphClient, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=go
graphClient.Me().SendMail().Post(context.Background(), requestBody, nil)

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Java**

```java

// Code snippets are only available for the latest version. Current version is 6.x

GraphServiceClient graphClient = new GraphServiceClient(requestAdapter);

com.microsoft.graph.users.item.sendmail.SendMailPostRequestBody sendMailPostRequestBody = new com.microsoft.graph.users.item.sendmail.SendMailPostRequestBody();
Message message = new Message();
message.setSubject("9/9/2018: concert");
ItemBody body = new ItemBody();
body.setContentType(BodyType.Html);
body.setContent("The group represents Nevada.");
message.setBody(body);
LinkedList<Recipient> toRecipients = new LinkedList<Recipient>();
Recipient recipient = new Recipient();
EmailAddress emailAddress = new EmailAddress();
emailAddress.setAddress("AlexW@contoso.com");
recipient.setEmailAddress(emailAddress);
toRecipients.add(recipient);
message.setToRecipients(toRecipients);
LinkedList<InternetMessageHeader> internetMessageHeaders = new LinkedList<InternetMessageHeader>();
InternetMessageHeader internetMessageHeader = new InternetMessageHeader();
internetMessageHeader.setName("x-custom-header-group-name");
internetMessageHeader.setValue("Nevada");
internetMessageHeaders.add(internetMessageHeader);
InternetMessageHeader internetMessageHeader1 = new InternetMessageHeader();
internetMessageHeader1.setName("x-custom-header-group-id");
internetMessageHeader1.setValue("NV001");
internetMessageHeaders.add(internetMessageHeader1);
message.setInternetMessageHeaders(internetMessageHeaders);
sendMailPostRequestBody.setMessage(message);
graphClient.me().sendMail().post(sendMailPostRequestBody);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**JavaScript**

```javascript

const options = {authProvider,
};

const client = Client.init(options);

const sendMail = {
  message: {
    subject: '9/9/2018: concert',
    body: {
      contentType: 'HTML',
      content: 'The group represents Nevada.'
    },
    toRecipients: [
      {
        emailAddress: {
          address: 'AlexW@contoso.com'
        }
      }
    ],
    internetMessageHeaders: [
      {
        name: 'x-custom-header-group-name',
        value: 'Nevada'
      },
      {
        name: 'x-custom-header-group-id',
        value: 'NV001'
      }
    ]
  }
};

await client.api('/me/sendMail').post(sendMail);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**PHP**

```php

<?php
use Microsoft\Graph\GraphServiceClient;
use Microsoft\Graph\Generated\Users\Item\SendMail\SendMailPostRequestBody;
use Microsoft\Graph\Generated\Models\Message;
use Microsoft\Graph\Generated\Models\ItemBody;
use Microsoft\Graph\Generated\Models\BodyType;
use Microsoft\Graph\Generated\Models\Recipient;
use Microsoft\Graph\Generated\Models\EmailAddress;
use Microsoft\Graph\Generated\Models\InternetMessageHeader;

$graphServiceClient = new GraphServiceClient($tokenRequestContext, $scopes);

$requestBody = new SendMailPostRequestBody();
$message = new Message();
$message->setSubject('9/9/2018: concert');
$messageBody = new ItemBody();
$messageBody->setContentType(new BodyType('hTML'));
$messageBody->setContent('The group represents Nevada.');
$message->setBody($messageBody);
$toRecipientsRecipient1 = new Recipient();
$toRecipientsRecipient1EmailAddress = new EmailAddress();
$toRecipientsRecipient1EmailAddress->setAddress('AlexW@contoso.com');
$toRecipientsRecipient1->setEmailAddress($toRecipientsRecipient1EmailAddress);
$toRecipientsArray []= $toRecipientsRecipient1;
$message->setToRecipients($toRecipientsArray);

$internetMessageHeadersInternetMessageHeader1 = new InternetMessageHeader();
$internetMessageHeadersInternetMessageHeader1->setName('x-custom-header-group-name');
$internetMessageHeadersInternetMessageHeader1->setValue('Nevada');
$internetMessageHeadersArray []= $internetMessageHeadersInternetMessageHeader1;
$internetMessageHeadersInternetMessageHeader2 = new InternetMessageHeader();
$internetMessageHeadersInternetMessageHeader2->setName('x-custom-header-group-id');
$internetMessageHeadersInternetMessageHeader2->setValue('NV001');
$internetMessageHeadersArray []= $internetMessageHeadersInternetMessageHeader2;
$message->setInternetMessageHeaders($internetMessageHeadersArray);

$requestBody->setMessage($message);

$graphServiceClient->me()->sendMail()->post($requestBody)->wait();

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**PowerShell**

```powershell

Import-Module Microsoft.Graph.Users.Actions

$params = @{message = @{	subject = "9/9/2018: concert"	body = @{		contentType = "HTML"		content = "The group represents Nevada."	}	toRecipients = @(		@{			emailAddress = @{				address = "AlexW@contoso.com"			}		}	)	internetMessageHeaders = @(		@{			name = "x-custom-header-group-name"			value = "Nevada"		}		@{			name = "x-custom-header-group-id"			value = "NV001"		}	)}
}

# A UPN can also be used as -UserId.
Send-MgUserMail -UserId $userId -BodyParameter $params

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Python**

```python

# Code snippets are only available for the latest version. Current version is 1.x
from msgraph import GraphServiceClient
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody
from msgraph.generated.models.message import Message
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.internet_message_header import InternetMessageHeader
# To initialize your graph_client, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=python
request_body = SendMailPostRequestBody(message = Message(	subject = "9/9/2018: concert",	body = ItemBody(		content_type = BodyType.Html,		content = "The group represents Nevada.",	),	to_recipients = [		Recipient(			email_address = EmailAddress(				address = "AlexW@contoso.com",			),		),	],	internet_message_headers = [		InternetMessageHeader(			name = "x-custom-header-group-name",			value = "Nevada",		),		InternetMessageHeader(			name = "x-custom-header-group-id",			value = "NV001",		),	],),
)

await graph_client.me.send_mail.post(request_body)

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

#### Response

```http
HTTP/1.1 202 Accepted
```

### Example 3: Create a message with a file attachment and send the message

#### Request

**HTTP**

```http
POST https://graph.microsoft.com/v1.0/me/sendMail
Content-type: application/json

{
  "message": {
    "subject": "Meet for lunch?",
    "body": {
      "contentType": "Text",
      "content": "The new cafeteria is open."
    },
    "toRecipients": [
      {
        "emailAddress": {
          "address": "meganb@contoso.com"
        }
      }
    ],
    "attachments": [
      {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": "attachment.txt",
        "contentType": "text/plain",
        "contentBytes": "SGVsbG8gV29ybGQh"
      }
    ]
  }
}
```

**C#**

```csharp

// Code snippets are only available for the latest version. Current version is 5.x

// Dependencies
using Microsoft.Graph.Me.SendMail;
using Microsoft.Graph.Models;

var requestBody = new SendMailPostRequestBody
{Message = new Message{	Subject = "Meet for lunch?",	Body = new ItemBody	{		ContentType = BodyType.Text,		Content = "The new cafeteria is open.",	},	ToRecipients = new List<Recipient>	{		new Recipient		{			EmailAddress = new EmailAddress			{				Address = "meganb@contoso.com",			},		},	},	Attachments = new List<Attachment>	{		new FileAttachment		{			OdataType = "#microsoft.graph.fileAttachment",			Name = "attachment.txt",			ContentType = "text/plain",			ContentBytes = Convert.FromBase64String("SGVsbG8gV29ybGQh"),		},	},},
};

// To initialize your graphClient, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=csharp
await graphClient.Me.SendMail.PostAsync(requestBody);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Go**

```go

// Code snippets are only available for the latest major version. Current major version is $v1.*

// Dependencies
import (  "context"  msgraphsdk "github.com/microsoftgraph/msgraph-sdk-go"  graphusers "github.com/microsoftgraph/msgraph-sdk-go/users"  graphmodels "github.com/microsoftgraph/msgraph-sdk-go/models"  //other-imports
)

requestBody := graphusers.NewItemSendMailPostRequestBody()
message := graphmodels.NewMessage()
subject := "Meet for lunch?"
message.SetSubject(&subject) 
body := graphmodels.NewItemBody()
contentType := graphmodels.TEXT_BODYTYPE 
body.SetContentType(&contentType) 
content := "The new cafeteria is open."
body.SetContent(&content) 
message.SetBody(body)

recipient := graphmodels.NewRecipient()
emailAddress := graphmodels.NewEmailAddress()
address := "meganb@contoso.com"
emailAddress.SetAddress(&address) 
recipient.SetEmailAddress(emailAddress)

toRecipients := []graphmodels.Recipientable {recipient,
}
message.SetToRecipients(toRecipients)

attachment := graphmodels.NewFileAttachment()
name := "attachment.txt"
attachment.SetName(&name) 
contentType := "text/plain"
attachment.SetContentType(&contentType) 
contentBytes := []byte("sGVsbG8gV29ybGQh")
attachment.SetContentBytes(&contentBytes) 

attachments := []graphmodels.Attachmentable {attachment,
}
message.SetAttachments(attachments)
requestBody.SetMessage(message)

// To initialize your graphClient, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=go
graphClient.Me().SendMail().Post(context.Background(), requestBody, nil)

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Java**

```java

// Code snippets are only available for the latest version. Current version is 6.x

GraphServiceClient graphClient = new GraphServiceClient(requestAdapter);

com.microsoft.graph.users.item.sendmail.SendMailPostRequestBody sendMailPostRequestBody = new com.microsoft.graph.users.item.sendmail.SendMailPostRequestBody();
Message message = new Message();
message.setSubject("Meet for lunch?");
ItemBody body = new ItemBody();
body.setContentType(BodyType.Text);
body.setContent("The new cafeteria is open.");
message.setBody(body);
LinkedList<Recipient> toRecipients = new LinkedList<Recipient>();
Recipient recipient = new Recipient();
EmailAddress emailAddress = new EmailAddress();
emailAddress.setAddress("meganb@contoso.com");
recipient.setEmailAddress(emailAddress);
toRecipients.add(recipient);
message.setToRecipients(toRecipients);
LinkedList<Attachment> attachments = new LinkedList<Attachment>();
FileAttachment attachment = new FileAttachment();
attachment.setOdataType("#microsoft.graph.fileAttachment");
attachment.setName("attachment.txt");
attachment.setContentType("text/plain");
byte[] contentBytes = Base64.getDecoder().decode("SGVsbG8gV29ybGQh");
attachment.setContentBytes(contentBytes);
attachments.add(attachment);
message.setAttachments(attachments);
sendMailPostRequestBody.setMessage(message);
graphClient.me().sendMail().post(sendMailPostRequestBody);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**JavaScript**

```javascript

const options = {authProvider,
};

const client = Client.init(options);

const sendMail = {
  message: {
    subject: 'Meet for lunch?',
    body: {
      contentType: 'Text',
      content: 'The new cafeteria is open.'
    },
    toRecipients: [
      {
        emailAddress: {
          address: 'meganb@contoso.com'
        }
      }
    ],
    attachments: [
      {
        '@odata.type': '#microsoft.graph.fileAttachment',
        name: 'attachment.txt',
        contentType: 'text/plain',
        contentBytes: 'SGVsbG8gV29ybGQh'
      }
    ]
  }
};

await client.api('/me/sendMail').post(sendMail);

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**PHP**

```php

<?php
use Microsoft\Graph\GraphServiceClient;
use Microsoft\Graph\Generated\Users\Item\SendMail\SendMailPostRequestBody;
use Microsoft\Graph\Generated\Models\Message;
use Microsoft\Graph\Generated\Models\ItemBody;
use Microsoft\Graph\Generated\Models\BodyType;
use Microsoft\Graph\Generated\Models\Recipient;
use Microsoft\Graph\Generated\Models\EmailAddress;
use Microsoft\Graph\Generated\Models\Attachment;
use Microsoft\Graph\Generated\Models\FileAttachment;

$graphServiceClient = new GraphServiceClient($tokenRequestContext, $scopes);

$requestBody = new SendMailPostRequestBody();
$message = new Message();
$message->setSubject('Meet for lunch?');
$messageBody = new ItemBody();
$messageBody->setContentType(new BodyType('text'));
$messageBody->setContent('The new cafeteria is open.');
$message->setBody($messageBody);
$toRecipientsRecipient1 = new Recipient();
$toRecipientsRecipient1EmailAddress = new EmailAddress();
$toRecipientsRecipient1EmailAddress->setAddress('meganb@contoso.com');
$toRecipientsRecipient1->setEmailAddress($toRecipientsRecipient1EmailAddress);
$toRecipientsArray []= $toRecipientsRecipient1;
$message->setToRecipients($toRecipientsArray);

$attachmentsAttachment1 = new FileAttachment();
$attachmentsAttachment1->setOdataType('#microsoft.graph.fileAttachment');
$attachmentsAttachment1->setName('attachment.txt');
$attachmentsAttachment1->setContentType('text/plain');
$attachmentsAttachment1->setContentBytes(\GuzzleHttp\Psr7\Utils::streamFor(base64_decode('SGVsbG8gV29ybGQh')));
$attachmentsArray []= $attachmentsAttachment1;
$message->setAttachments($attachmentsArray);

$requestBody->setMessage($message);

$graphServiceClient->me()->sendMail()->post($requestBody)->wait();

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**PowerShell**

```powershell

Import-Module Microsoft.Graph.Users.Actions

$params = @{message = @{	subject = "Meet for lunch?"	body = @{		contentType = "Text"		content = "The new cafeteria is open."	}	toRecipients = @(		@{			emailAddress = @{				address = "meganb@contoso.com"			}		}	)	attachments = @(		@{			"@odata.type" = "#microsoft.graph.fileAttachment"			name = "attachment.txt"			contentType = "text/plain"			contentBytes = "SGVsbG8gV29ybGQh"		}	)}
}

# A UPN can also be used as -UserId.
Send-MgUserMail -UserId $userId -BodyParameter $params

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

**Python**

```python

# Code snippets are only available for the latest version. Current version is 1.x
from msgraph import GraphServiceClient
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody
from msgraph.generated.models.message import Message
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.attachment import Attachment
from msgraph.generated.models.file_attachment import FileAttachment
# To initialize your graph_client, see https://learn.microsoft.com/en-us/graph/sdks/create-client?from=snippets&tabs=python
request_body = SendMailPostRequestBody(message = Message(	subject = "Meet for lunch?",	body = ItemBody(		content_type = BodyType.Text,		content = "The new cafeteria is open.",	),	to_recipients = [		Recipient(			email_address = EmailAddress(				address = "meganb@contoso.com",			),		),	],	attachments = [		FileAttachment(			odata_type = "#microsoft.graph.fileAttachment",			name = "attachment.txt",			content_type = "text/plain",			content_bytes = base64.urlsafe_b64decode("SGVsbG8gV29ybGQh"),		),	],),
)

await graph_client.me.send_mail.post(request_body)

```

> 
> For details about how to [add the SDK](/en-us/graph/sdks/sdk-installation) to your project and [create an authProvider](/en-us/graph/sdks/choose-authentication-providers) instance, see the [SDK documentation](/en-us/graph/sdks/sdks-overview).

#### Response

```http
HTTP/1.1 202 Accepted
```

### Example 4: Send a new message using MIME format

#### Request

```http
POST https://graph.microsoft.com/v1.0/me/sendMail
Content-type: text/plain

RnJvbTogQWRlbGUgVmFuY2UgPEFkZWxlVkBjb250b3NvLmNvbT4KVG86IEFsZXggV2lsYmVyIDxB
bGV4V0Bjb250b3NvLmNvbT4KU3ViamVjdDpUZXN0IE1lc3NhZ2UKQ29udGVudC1UeXBlOiBtdWx0
aXBhcnQvbWl4ZWQ7Cglib3VuZGFyeT0iXzAwNF9UWVpQUjA0TUI2OTgxNzNGRDAwMjE1MkQ1QURC
OEZCNDdDOEJDQVRZWlBSMDRNQjY5ODFhcGNwXyIKTUlNRS1WZXJzaW9uOiAxLjAKCi0tXzAwNF9U
WVpQUjA0TUI2OTgxNzNGRDAwMjE1MkQ1QURCOEZCNDdDOEJDQVRZWlBSMDRNQjY5ODFhcGNwXwpD
b250ZW50LVR5cGU6IG11bHRpcGFydC9hbHRlcm5hdGl2ZTsKCWJvdW5kYXJ5PSJfMDAwX1RZWlBS
MDRNQjY5ODE3M0ZEMDAyMTUyRDVBREI4RkI0N0M4QkNBVFlaUFIwNE1CNjk4MWFwY3BfIgoKLS1f
MDAwX1RZWlBSMDRNQjY5ODE3M0ZEMDAyMTUyRDVBREI4RkI0N0M4QkNBVFlaUFIwNE1CNjk4MWFw
Y3BfCkNvbnRlbnQtVHlwZTogdGV4dC9wbGFpbjsgY2hhcnNldD0iaXNvLTg4NTktMSIKQ29udGVu
dC1UcmFuc2Zlci1FbmNvZGluZzogcXVvdGVkLXByaW50YWJsZQoKdGVzdCB0ZXh0IGJvZHkKCgot
LV8wMDBfVFlaUFIwNE1CNjk4MTczRkQwMDIxNTJENUFEQjhGQjQ3QzhCQ0FUWVpQUjA0TUI2OTgx
YXBjcF8KQ29udGVudC1UeXBlOiB0ZXh0L2h0bWw7IGNoYXJzZXQ9Imlzby04ODU5LTEiCkNvbnRl
bnQtVHJhbnNmZXItRW5jb2Rpbmc6IHF1b3RlZC1wcmludGFibGUKCjxodG1sPgo8aGVhZD4KPC9o
ZWFkPgo8Ym9keT4KdGVzdCBodG1sIGJvZHkKPC9ib2R5Pgo8L2h0bWw+CgotLV8wMDBfVFlaUFIw
NE1CNjk4MTczRkQwMDIxNTJENUFEQjhGQjQ3QzhCQ0FUWVpQUjA0TUI2OTgxYXBjcF8tLQoKLS1f
MDA0X1RZWlBSMDRNQjY5ODE3M0ZEMDAyMTUyRDVBREI4RkI0N0M4QkNBVFlaUFIwNE1CNjk4MWFw
Y3BfCkNvbnRlbnQtVHlwZTogdGV4dC9wbGFpbjsKQ29udGVudC1EaXNwb3NpdGlvbjogYXR0YWNo
bWVudDsKICAgICAgICBmaWxlbmFtZT0idGVzdC50eHQiCgp0aGlzIGlzIHRoZSBhdHRhY2htZW50
IHRleHQKCi0tXzAwNF9UWVpQUjA0TUI2OTgxNzNGRDAwMjE1MkQ1QURCOEZCNDdDOEJDQVRZWlBS
MDRNQjY5ODFhcGNwXy0t

```

#### Response

```http
HTTP/1.1 202 Accepted
```

If the request body includes malformed MIME content, this method returns the following error message.

```http
HTTP/1.1 400 Bad Request
Content-type: application/json

{
  "error": {
    "code": "ErrorMimeContentInvalidBase64String",
    "message": "Invalid base64 string for MIME content."
  }
}
```

### Example 5: Send a new message flagged for follow-up

#### Request

```http
POST https://graph.microsoft.com/v1.0/me/sendMail
Content-type: application/json

{
  "subject": "Please respond by Friday",
  "toRecipients": [
    {
      "emailAddress": {
        "address": "meganb@contoso.com"
      }
    }
  ],
  "flag": {
    "flagStatus": "flagged",
    "startDateTime": {
      "dateTime": "2023-08-30T12:13:00",
      "timeZone": "Eastern Standard Time"
    },
    "dueDateTime": {
      "dateTime": "2023-09-01T17:00:00",
      "timeZone": "Eastern Standard Time"
    }
  }
}
```

#### Response

```http
HTTP/1.1 202 Accepted
```

---

## Other Supported Versions

- [graph-rest-beta](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-beta&accept=text/markdown)
